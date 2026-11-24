# NBP_WebApp - kurs USD (NBP) na GKE
 
Prosta aplikacja webowa (Python/Flask) pokazująca aktualny kurs średni USD z **tabeli A NBP**
(NBP Web API: `https://api.nbp.pl/api/exchangerates/rates/a/usd/`), zbudowana, wdrażana i uruchamiana na
**GKE** przy użyciu **Dockera, Helma i GitHub Actions**.
 
## Struktura repozytorium
 
```

├── app/                    # aplikacja (Flask), testy, zależności
│   ├── app.py              # endpointy: /, /api/rate, /healthz + logi JSON
│   ├── nbp_client.py       # klient NBP: retry, timeout, cache TTL, fallback
│   ├── templates/index.html
│   └── tests/test_app.py
├── Dockerfile              # multi-stage, użytkownik non-root
├── helm/nbp-webapp/        # chart: Deployment, Service, Ingress, HPA, PDB
└── .github/workflows/ci-cd.yaml
```
 
## Szybki start lokalnie
 
```bash
pip install -r app/requirements-dev.txt
pytest app/tests
cd app && python -m flask --app app run --port 8080      # http://localhost:8080
 
# lub w Dockerze
docker build -t nbp-webapp .
docker run --rm -p 8080:8080 nbp-webapp
```
 
## Uruchomienie na GCP - krok po kroku
 
Wymagane: konto GCP z projektem i włączonym billingiem, repozytorium na GitHubie oraz (opcjonalnie)
`gcloud`, `kubectl` i `helm` do ręcznej obsługi.
 
### 1. Projekt i API
 
W konsoli GCP (https://console.cloud.google.com):
- wybierz lub utwórz projekt i podepnij konto rozliczeniowe (☰ -> **Billing**),
- ☰ -> **APIs & Services** -> **Library** -> włącz: **Kubernetes Engine API**, **Artifact Registry API**,
  **IAM Service Account Credentials API**, **Security Token Service API** (dwa ostatnie dla Workload Identity Federation).

### 2. Rejestr obrazów (Artifact Registry)
 
☰ -> **Artifact Registry** -> **Repositories** -> **Create repository**:
nazwa `nbp-webapp`, format **Docker**, tryb Standard, region `europe-central2`.
 
### 3. Klaster GKE
 
☰ -> **Kubernetes Engine** -> **Clusters** -> **Create** -> tryb **Autopilot**:
nazwa `nbp-webapp-cluster`, region `europe-central2`.
 
Węzły klastra pobierają obrazy z Artifact Registry za pomocą swojego konta serwisowego (domyślnie
`NUMER_PROJEKTU-compute@developer.gserviceaccount.com`). W nowszych projektach konto to może nie mieć żadnych ról,
co objawia się błędem `Cannot pull image`. Nadaj mu uprawnienia (☰ -> **IAM & Admin** -> **IAM** -> **Grant access**):
**Artifact Registry Reader** oraz **Kubernetes Engine Default Node Service Account**.
 
### 4. Dostęp dla pipeline'u (Workload Identity Federation, bez kluczy JSON)
 
1. **Konto serwisowe**: ☰ -> **IAM & Admin** -> **Service Accounts** -> **Create**: `github-cicd`
   z rolami **Artifact Registry Writer** i **Kubernetes Engine Developer**.
2. **Pula i provider**: ☰ -> **IAM & Admin** -> **Workload Identity Federation** -> **Create pool**:
   - pula: `github-pool`,
   - provider typu **OIDC**: `github-provider`, issuer `https://token.actions.githubusercontent.com`,
   - mapowania: `google.subject = assertion.sub` oraz `attribute.repository = assertion.repository`,
   - warunek (Attribute conditions): `assertion.repository == "OWNER/REPO"`.
3. **Grant access**: w puli -> **Grant access** -> *Service Account impersonation* -> konto `github-cicd`,
   atrybut `repository` = `OWNER/REPO`. Dzięki temu tylko to repozytorium może uwierzytelnić się jako konto `github-cicd`.

### 5. Zmienne w GitHub
 
W repozytorium: *Settings -> Secrets and variables -> Actions -> **Variables** (Repository variables)*:
 
| Zmienna | Wartość |
|---|---|
| `GCP_PROJECT_ID` | Project ID |
| `GCP_REGION` | `europe-central2` |
| `GKE_CLUSTER` | `nbp-webapp-cluster` |
| `AR_REPOSITORY` | `nbp-webapp` |
| `WIF_PROVIDER` | `projects/NUMER_PROJEKTU/locations/global/workloadIdentityPools/github-pool/providers/github-provider` |
| `WIF_SERVICE_ACCOUNT` | `github-cicd@PROJECT_ID.iam.gserviceaccount.com` |
 
Opcjonalnie utwórz środowisko `production` (Settings -> Environments) i dodaj *Required reviewers*,
aby wdrożenie wymagało ręcznej akceptacji. Bez tego GitHub utworzy je automatycznie, bez reguł ochrony.
 
### 6. Wdrożenie
 
`git push` na `main` uruchamia pipeline. Adres aplikacji (Service typu LoadBalancer):
 
```bash
gcloud container clusters get-credentials nbp-webapp-cluster --region europe-central2
kubectl -n nbp-webapp get svc nbp-webapp   # kolumna EXTERNAL-IP
```
 
### Ręczne wdrożenie Helmem (bez pipeline)
 
```bash
REG=europe-central2-docker.pkg.dev/<id-projektu>/nbp-webapp
gcloud auth configure-docker europe-central2-docker.pkg.dev
docker build -t $REG/nbp-webapp:v1 . && docker push $REG/nbp-webapp:v1
helm upgrade --install nbp-webapp helm/nbp-webapp -n nbp-webapp --create-namespace \
  --set image.repository=$REG/nbp-webapp --set image.tag=v1
```
 
### Ingress zamiast LoadBalancera
 
```bash
helm upgrade --install nbp-webapp helm/nbp-webapp -n nbp-webapp --reuse-values \
  --set service.type=ClusterIP --set ingress.enabled=true --set ingress.className=gce
```
(dla NGINX: zainstaluj `ingress-nginx` i ustaw `ingress.className=nginx`.)
 
### Sprzątanie
 
```bash
helm uninstall nbp-webapp -n nbp-webapp
```
Klaster, repozytorium Artifact Registry, pulę WIF i konto `github-cicd` usuń w konsoli GCP.
 
## Konfiguracja Helm (`values.yaml`)
 
Najważniejsze parametry: `image.repository`, `image.tag`, `replicaCount` (gdy HPA wyłączone),
`autoscaling.*`, `service.type`, `ingress.*`, `resources`, `config.cacheTtlSeconds`, `config.nbpApiUrl`.
Domyślnie kontener działa jako zwykły użytkownik (nie root), z systemem plików tylko do odczytu i bez dodatkowych uprawnień systemowych.
 
## Pipeline CI/CD (`.github/workflows/ci-cd.yaml`)
 
| Job | Kiedy | Co robi |
|---|---|---|
| `test` | PR i push | `pytest`, `helm lint` |
| `build-push` | PR i push | build obrazu, na `main` push do Artifact Registry (tagi: skrót SHA + `latest`) |
| `deploy` | tylko `main` | uwierzytelnienie WIF -> `get-gke-credentials` -> `helm upgrade --install --atomic --wait` |
 
Obraz jest wdrażany po **niezmiennym tagu SHA** (nie `latest`), dzięki czemu każde wdrożenie jest
odtwarzalne, a `--atomic` automatycznie cofa release przy nieudanym rollout.
 
## Decyzje technologiczne
 
- **Flask + gunicorn** - minimum kodu, łatwe testowanie oraz dane renderowane po stronie serwera (HTML).
  Gunicorn zamiast serwera deweloperskiego Flaska, bo jest przeznaczony na produkcję (wiele workerów, restart niedziałających).
- **NBP Web API (JSON)** zamiast scrapowania strony, użycie oficjalnego źródła.
- **Cache TTL (domyślnie 15 min)** - NBP publikuje kurs raz dziennie, więc nie ma sensu odpytywać go przy każdym żądaniu.
  Cache jest w pamięci procesu (per worker).
- **Obsługa błędów NBP** - timeout, ponawianie z rosnącym odstępem czasowym, przy awarii zwracany jest ostatni znany kurs z ostrzeżeniem, a bez cache'u - strona z błędem i HTTP 503.
- **Probes `/healthz` niezależne od NBP** - awaria zewnętrznego API nie powoduje restartów ani wyłączenia podów z ruchu.
- **GKE Autopilot** - brak zarządzania węzłami, HPA i logowanie działają od razu, rozliczanie za zasoby podów.
- **Workload Identity Federation** - pipeline loguje się do GCP bez kluczy JSON, dostęp ograniczony do jednego repozytorium.
- **Logi JSON na stdout** z polem `severity` - automatycznie trafiają do **Cloud Logging**
  (Logs Explorer: `resource.type="k8s_container" resource.labels.namespace_name="nbp-webapp"`).
- **Helm** dla zasobów Kubernetes, infrastruktura GCP konfigurowana ręcznie w konsoli.
## Uproszczenia i dalsze kroki
 
- Infrastruktura GCP jest tworzona ręcznie - nie jest opisana kodem, więc trudniej ją odtworzyć. Naturalnym krokiem jest IaC.
- Domyślnie ekspozycja przez `LoadBalancer` po HTTP, Ingress jest gotowy w chartcie, ale bez TLS
  (produkcyjnie: domena + `ManagedCertificate` lub cert-manager).
- Cache per proces - przy większej skali można użyć Redis.
- Brak osobnych środowisk (dev/stage/prod) - można dodać kolejne pliki `values-*.yaml`.
- Do rozważenia: skan obrazu (Trivy lub skaner Prisma Cloud), NetworkPolicy.
 