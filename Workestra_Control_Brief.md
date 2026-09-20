# Workestra Control — Product & Implementation Brief

## 1. Amaç

`Local-Ai-Workestra` şu anda çalışan bir local coding-agent motorudur. Bu dokümanın amacı yeni bir agent framework yazmak değil, mevcut motorun üzerine günlük kullanım için bir **control plane / control center** eklemektir.

Hedef deneyim:

1. Kullanıcı proje fikrini ChatGPT/Codex/Sol gibi güçlü bir modele anlatır.
2. Dış model yalnızca kaba bir `PLAN.md` üretir. Workestra'nın iç şemasını bilmek zorunda değildir.
3. Kullanıcı Workestra Control içinden proje seçer veya yeni proje oluşturur.
4. `PLAN.md` dosyasını sürükler/yapıştırır.
5. Local **Plan Intake / Plan Compiler** agent kaba planı Workestra'nın strict Plan v2 formatına dönüştürür.
6. Deterministic validator planı dependency, cycle, risk, task-kind ve safety açısından doğrular.
7. Kullanıcı görsel planda görevleri görür ve `Start` der.
8. Mevcut orchestrator motoru Qwen3-Coder / GPT-OSS / Bonsai 2 / Devstral routing'iyle çalışır.
9. UI yalnızca motoru yönetir ve gözlemler: run state, task graph, logs/events, approvals, diffs, tests, checkpoints, metrics.
10. Kullanıcı terminal komutlarını ezberlemek zorunda kalmaz.

Ana ilke:

> **UI yeni bir orchestrator olmamalı. Mevcut orchestrator tek execution engine ve tek güvenlik kaynağı olarak kalmalı.**

---

## 2. Mevcut Sistemin Korunması Gereken Güçlü Tarafları

Repo'nun mevcut belgelerine göre Workestra zaten aşağıdaki mekanizmalara sahip:

- Clean target workspace zorunluluğu.
- `agent/<run-id>` branch izolasyonu.
- Plan v2 task graph ve deterministic topological execution.
- Approval / resume.
- Baseline-aware verification.
- Semantic edit operations ve exact-match edit uygulama.
- Strict Git validation.
- Rollback / checkpoint.
- Metrics, trajectory ve retrospective artifact'ları.
- Sequential model lifecycle ve resource guard.
- Fail-closed security/review davranışı.
- Aktif fleet:
  - Qwen3-Coder → primary coder / explorer
  - GPT-OSS → diagnosis / optimization / primary security review
  - Bonsai 2 → deep reasoning / architecture / retrospective
  - Devstral → fallback coder

Control layer bunların hiçbirini bypass etmemeli.

---

## 3. Genişletilmiş Araştırmadan Alınacak Tasarım Dersleri

### 3.1 OpenHands — API ile execution engine'i UI'dan ayır

OpenHands Agent Server ayrı bir REST/WebSocket kontrol katmanı kullanıyor. Conversation create/get, pause, resume, event query, confirmation response ve gerçek-zamanlı event stream ayrı API yüzeyleri olarak sunuluyor.

Workestra için alınacak ders:

- UI orchestrator process'inin içine gömülü mantık yazmamalı.
- `Project / Plan / Run / Task / Approval / Event` için küçük bir local API oluştur.
- Start, pause, resume, approve/reject HTTP endpoint'leri olsun.
- Execution event'leri UI'ya stream edilsin.
- Mevcut Python servisleri doğrudan çağrılsın; CLI çıktısı parse edilerek ikinci bir execution sistemi yaratılmasın.

Kaynak:
https://github.com/OpenHands/OpenHands-Server
https://docs.openhands.dev/

### 3.2 LangGraph — state, interrupt ve resume birinci sınıf kavramlar olsun

LangGraph'in iyi yaptığı şey agent execution'ı discrete node/state olarak göstermesi. Human-in-the-loop `interrupt()` ile run duruyor, checkpoint ile state saklanıyor ve daha sonra aynı noktadan devam ediyor. Ayrıca client bağlantısı koptuğunda çalışan stream'e tekrar bağlanma modeli mevcut.

Workestra için alınacak ders:

- UI state'i "terminal çıktısı"ndan türetilmemeli; run/task state authoritative olmalı.
- `WAITING_FOR_APPROVAL`, `RUNNING`, `FAILED`, `PASSED`, `BLOCKED`, `SKIPPED` gibi state'ler doğrudan UI modeline taşınmalı.
- Browser kapanması run'ı durdurmamalı.
- UI tekrar açılınca mevcut run state + event offset üzerinden yeniden bağlanabilmeli.
- Task graph görünümü Plan v2 dependency graph'tan doğrudan üretilebilir.

Kaynak:
https://docs.langchain.com/oss/javascript/langgraph/thinking-in-langgraph
https://docs.langchain.com/oss/javascript/langchain/frontend/join-rejoin

### 3.3 Prefect — proje/run history ve state merkezli dashboard

Prefect modern orchestration UI'sında run state, retry, real-time monitoring, logs ve DAG görünümünü temel deneyim yapıyor.

Workestra için alınacak ders:

- Ana ekran "agents" değil **Projects → Runs → Tasks** hiyerarşisiyle kurulmalı.
- Her project için latest run, current branch, clean/dirty repo, configured verifier, fleet health ve last success/failure gösterilebilir.
- Run listesi filtrelenebilir olmalı: running / waiting / passed / failed.
- "Retry" semantiği kör yeniden çalıştırma değil, mevcut Workestra checkpoint/rollback kurallarına bağlı olmalı.

Kaynak:
https://docs.prefect.io/

### 3.4 CrewAI / AgentOps — observability timeline'ı ayrı bir ürün yüzeyi yap

CrewAI tracing agent decisions, task timeline, tool usage, LLM calls, timings ve errors gösteriyor. AgentOps ise bir execution session'ını agent, LLM, action, tool ve error event'leri altında topluyor ve replay/export yaklaşımı kullanıyor.

Workestra için alınacak ders:

- Her run tek bir `run_id` ile gözlemlenmeli.
- UI'da ayrı bir **Trace / Timeline** sekmesi olmalı.
- Her event en az timestamp, run_id, task_id, model/actor, event_type, status, duration, short message ve artifact reference taşımalı.
- Raw chain-of-thought gösterilmemeli. UI yalnızca action, decision summary, tool/model event, test sonucu ve authoritative state göstermeli.
- Mevcut `trajectory.jsonl` ilk veri kaynağı olarak yeniden kullanılabilir.

Kaynak:
https://docs.crewai.com/
https://github.com/AgentOps-AI/agentops

### 3.5 n8n — execution history ve geçmiş run UX'i

n8n execution history içinde status filtresi, failed execution retry ve geçmiş execution data'sını tekrar açma gibi UX kalıpları kullanıyor.

Workestra için alınacak ders:

- Kullanıcı eski run'ı seçip planı, changed files, tests, findings, retrospective, branch/commit ve timeline görebilmeli.
- Run artifacts silinip kaybolmamalı.
- Retry yapılırken hangi state/checkpoint'ten devam edildiği açıkça görünmeli.

Kaynak:
https://docs.n8n.io/workflows/executions/all-executions/

### 3.6 AutoGen Studio — UI yararlı, fakat execution engine ile karıştırma

AutoGen Studio web tabanlı agent/team workflow prototyping UI'sı sunuyor, fakat kendi dokümanında production-ready olmadığını açıkça belirtiyor.

Workestra için alınacak ders:

- Studio/canvas fikrini al.
- AutoGen Studio'yu dependency veya mimari temel yapma.
- Workestra'nın güvenlik ve execution invariants'ını değiştirme.
- Drag-and-drop team builder MVP için gereksiz.

Kaynak:
https://github.com/microsoft/autogen

### 3.7 Temporal — durable execution fikrini al, dependency'yi alma

Temporal durable workflows için crash sonrası state'ten devam etmeyi temel özellik yapıyor. Bu Workestra'nın checkpoint/resume yönüyle aynı problem alanına dokunuyor.

Workestra için alınacak ders:

- Run state disk üzerinde durable olmalı.
- UI process'i veya browser kapanması execution state'i bozmamalı.
- Ancak local, tek-kullanıcılı Workestra v1.1 için Temporal gibi ayrı orchestration altyapısı eklemek gereksiz complexity olur.
- Mevcut run state/checkpoint mekanizması geliştirilerek devam edilmeli.

Kaynak:
https://docs.temporal.io/

### 3.8 OpenTelemetry — geleceğe uygun trace modeli

OpenTelemetry trace → span → logs/events modeli, run/task/model/tool ilişkisinin standart bir şekilde modellenmesi için iyi referans.

Workestra için alınacak ders:

- Şimdilik OTel dependency eklemek zorunlu değil.
- Fakat internal event schema daha sonra OTel'e map edilebilecek şekilde tasarlanmalı.
- 2026 yönlendirmesinde yeni event üretiminde trace ile korele log yaklaşımı önem kazanıyor; dolayısıyla her şeyi özel span-event formatına kilitleme.

Kaynak:
https://opentelemetry.io/docs/concepts/signals/traces/
https://opentelemetry.io/blog/2026/deprecating-span-events/

---

## 4. Önerilen Ürün: `Workestra Control`

### MVP ana ekranları

#### A. Projects

Her kayıt:
- Project name
- Repo path
- Git branch
- clean / dirty status
- verifier/test command
- latest run
- active run
- local model health

Actions:
- Add Existing Project
- New Project (ilk milestone'da şart değil)
- Open Project
- Import Plan
- Start Task

#### B. Plan Intake

Input seçenekleri:
- `.md` sürükle-bırak
- file picker
- Markdown paste

Akış:

`Rough Markdown → Plan Compiler → Plan v2 → Deterministic Validation → Human Preview`

Preview:
- milestones
- tasks
- dependencies
- risk
- approvals
- task kinds
- acceptance criteria
- test strategy

Kullanıcı planı onaylamadan execution başlamamalı.

#### C. Run View

Üst bilgi:
- project
- run id
- branch
- elapsed time
- status
- current model
- current task

Task graph:
- DONE
- RUNNING
- WAITING
- BLOCKED
- SKIPPED
- FAILED
- APPROVAL_REQUIRED

Actions:
- Pause
- Resume
- Stop/Cancel
- Approve
- Reject

#### D. Console / Timeline

Gerçek zamanlı, okunabilir event stream:
- model started/stopped
- repository evidence collected
- semantic edit accepted/rejected
- verifier started/completed
- test summary
- security review result
- fallback triggered
- checkpoint created
- rollback performed
- approval requested

Raw private reasoning/chain-of-thought gösterme.

#### E. Changes

- changed file list
- git diff
- checkpoint commit
- branch
- verification result
- security findings

#### F. Run History

- timestamp
- project
- plan
- status
- duration
- task success count
- branch/commit
- open artifacts

---

## 5. Plan Compiler Tasarımı

Bu sistemin kullanıcı açısından en kritik yeni parçası budur.

### Input

Kötü veya kaba Markdown kabul et. Dış modelin strict JSON üretmesini bekleme.

### Compiler

İlk tercih:
- Bonsai 2: architecture/deep reasoning rolü nedeniyle plan normalization için uygun.
- Plan compiler'ın model output'u doğrudan execution yapamaz.

Compiler output:
- strict Plan v2 candidate
- explicit assumptions
- unresolved questions
- risk classification
- dependencies
- acceptance criteria

### Deterministic gate

Modelden sonra mutlaka mevcut Plan v2 validator:
- invalid task kind → reject
- missing dependency → reject
- self dependency → reject
- cycle → reject
- unsafe path/operation metadata → reject
- executable arbitrary shell command → reject
- high/critical risk → approval required

### Önemli güvenlik kuralı

**Imported plan untrusted input'tur.**

Markdown içinden gelen hiçbir metin shell command, production deploy, VPS access, main merge, arbitrary dependency install veya verifier override olarak otomatik yürütülmemeli.

Global trusted verifier proje ayarından gelmeli. Plan içindeki `verification` yalnızca informational metadata olarak kalmalı.

---

## 6. Control API Mimarisi

Öneri: mevcut Python motorunun üzerine ince local API.

### İlk API yüzeyi

```text
GET  /api/health
GET  /api/projects
POST /api/projects
GET  /api/projects/{id}

POST /api/plans/import
POST /api/plans/{id}/compile
GET  /api/plans/{id}

POST /api/runs
GET  /api/runs
GET  /api/runs/{id}

POST /api/runs/{id}/pause
POST /api/runs/{id}/resume
POST /api/runs/{id}/cancel

POST /api/runs/{id}/approvals/{approval_id}/approve
POST /api/runs/{id}/approvals/{approval_id}/reject

GET  /api/runs/{id}/events
GET  /api/runs/{id}/diff
GET  /api/runs/{id}/artifacts
```

### Streaming

MVP için **SSE (Server-Sent Events)** tercih edilebilir:
- Event trafiği esas olarak server → UI.
- Start/pause/resume/approve HTTP POST ile yapılabilir.
- SSE daha basit.
- `Last-Event-ID` mantığıyla reconnect kolaydır.

İleride gerçek duplex terminal veya interactive shell gerekirse WebSocket eklenebilir.

### Backend

Öneri:
- mevcut Python package aynı kalır
- ince FastAPI (veya eşdeğer minimal ASGI layer)
- execution logic API layer içinde yeniden yazılmaz
- CLI ve UI aynı application-service fonksiyonlarını çağırır

Hedef:

```text
CLI ──────┐
          ├── Application Services ── Existing Orchestrator Engine
Web UI ───┘
```

Kaçınılacak mimari:

```text
Web UI → subprocess → CLI stdout parser → duplicated state
```

---

## 7. Persistence

MVP'de gereksiz database projesi açma.

### Authoritative source

Mevcut run artifacts authoritative kalmalı:
- plan
- state
- trajectory
- metrics
- retrospective
- audit
- Git branch/checkpoint

### Project registry

Basit seçenek:
`~/.config/workestra/projects.json`

veya küçük SQLite registry.

Tercih:
- Project registry için SQLite kabul edilebilir.
- Run execution state'i yeniden SQLite'a kopyalayıp iki ayrı source-of-truth yaratma.
- UI index/cache türetebilir; authoritative run files motorun mevcut formatında kalır.

---

## 8. UI Teknoloji Tavsiyesi

MVP:
- Backend: Python / ASGI
- Frontend: küçük React/Vite veya benzer hafif SPA
- Task graph: ilk sürüm CSS/HTML ile bile olabilir; daha sonra graph layer eklenebilir
- Streaming: SSE
- Local only: `127.0.0.1`
- Bir komut: `uv run workestra`

Komut:
1. backend başlatır
2. uygun local port seçer
3. browser açar
4. control UI sunar

Desktop packaging sonraya bırakılmalı.

---

## 9. Güvenlik Invariants — Kesinlikle Bozulmamalı

1. Dirty workspace üzerinde otomatik çalışma yok.
2. Main branch üzerinde doğrudan agent edit yok.
3. `agent/<run-id>` izolasyonu korunur.
4. Imported plan shell command çalıştıramaz.
5. Plan verifier command belirleyemez.
6. Model arbitrary dependency install yaptıramaz.
7. High/critical risk approval gate korunur.
8. Security/reviewer error fail-closed kalır.
9. Invalid/malformed semantic edits write öncesi reddedilir.
10. Failed attempt rollback korunur.
11. Successful checkpoint olmadan task PASS sayılmaz.
12. Browser kapanması execution state'i bozmaz.
13. UI approval olmadan approval-gated task ilerlemez.
14. UI model reasoning/hidden chain-of-thought göstermeye çalışmaz.
15. Local server varsayılan olarak yalnızca `127.0.0.1` bind eder.
16. Production/VPS/deploy capability MVP'ye eklenmez.

---

## 10. Uygulama Milestone'ları

### M1 — Application Service + Local Control API

Deliverables:
- reusable application-service interface
- project registry
- run list/detail
- start/pause/resume/approve/reject
- existing artifacts reader
- event streaming
- tests

Acceptance:
- CLI davranışı bozulmaz
- UI API aynı orchestrator motorunu kullanır
- disposable run API'dan başlatılıp izlenebilir
- browser/client disconnect run state'i bozmaz

### M2 — Plan Intake / Compiler

Deliverables:
- Markdown upload/paste
- stored rough plan
- Bonsai plan normalization
- strict Plan v2 candidate
- deterministic validator
- plan preview
- unresolved issue handling

Acceptance:
- kötü Markdown → geçerli plan veya kontrollü reject
- compiler output hiçbir zaman validator bypass edemez
- imported arbitrary commands execute edilmez

### M3 — Minimal Web UI

Deliverables:
- Projects
- Plan import/preview
- Run detail
- Task status
- Console/timeline
- Approval controls
- Changes/diff
- Run history

Acceptance:
Kullanıcı terminal komutu hatırlamadan:
`project select → plan import → compile → preview → start → observe → approve → finish`
akışını tamamlar.

### M4 — New Project Wizard

İlk template yalnızca güvenli desteklenen stack ile başlasın.
Örnek:
- Python + uv
- Git init
- pyproject.toml
- uv.lock
- tests baseline
- initial commit

Daha sonra FastAPI, Node, React, Godot, Empty Git repository eklenebilir.

### M5 — Polish (MVP sonrasında)

- graph canvas
- richer metrics
- run compare
- notifications
- project templates
- desktop package
- agent avatars / pixel office / visual animations

Bunlar ilk kullanım deneyimini geciktirmemeli.

---

## 11. MVP'de Yapılmaması Gerekenler

- Yeni agent framework yazma.
- LangGraph/CrewAI/AutoGen'e migrate etme.
- Temporal ekleme.
- Kubernetes/Docker worker platformu kurma.
- Multi-user auth sistemi yapma.
- Cloud deployment yapma.
- Model routing'i tekrar tasarlama.
- Pixel-office UI ile başlama.
- Full terminal emulator ekleme.
- Arbitrary command runner yapma.
- Main branch auto-merge ekleme.
- Production deployment ekleme.
- Mevcut Plan v2 yerine başka DSL üretme.

---

## 12. Paralel Geliştirme İçin Workstream'ler

### Stream A — Existing Engine/API Audit
- current CLI entrypoints
- PlanRunner
- control/resume
- run artifact layout
- application-service extraction boundary

### Stream B — Plan Intake
- Markdown ingestion
- compiler prompt/schema
- validator integration
- security tests

### Stream C — Control API
- endpoints
- run lifecycle
- SSE event stream
- reconnect behavior
- local binding

### Stream D — Frontend
- projects
- plan preview
- run/task view
- timeline
- approvals
- diff view

### Stream E — Verification & Safety
- regression suite
- disconnect/resume
- dirty repo
- approval bypass attempts
- malicious imported plan
- malformed model output
- process cleanup

Streams aynı dosyalarda çatışmamalı. Önce lead agent component boundaries ve interface contracts belirlemeli, sonra sub-agent'lar paralel çalışmalı.

---

## 13. İlk Release İçin Done Tanımı

Workestra Control v1.1 aşağıdaki demo tek seferde geçerse kullanılabilir sayılır:

1. `uv run workestra`
2. browser açılır
3. mevcut repo eklenir
4. kaba `PLAN.md` import edilir
5. Bonsai planı Plan v2'ye normalize eder
6. deterministic validation geçer
7. kullanıcı plan preview görür
8. run başlatılır
9. Qwen coding yapar
10. test çalışır
11. security gerektiğinde GPT-OSS çalışır
12. Qwen fail senaryosunda Devstral fallback gözlenir
13. approval gereken task UI'da durur
14. approve sonrası aynı run devam eder
15. browser refresh/reconnect state kaybetmez
16. final diff/test/security/checkpoint sonucu görüntülenir
17. model process'leri kapanır
18. target main değişmez

Bu demo geçmeden visual polish'e geçme.

---

## 14. Implementation Agent İçin Son Talimat

Bu brief bir fikir listesi değildir; mevcut Workestra motorunun üzerine eklenmesi gereken **ürün kullanım katmanının hedef tanımıdır**.

Implementation sırasında:

1. Önce repo'yu ve `PROGRESS.md`, `README.md`, `HANDOFF.md` belgelerini incele.
2. Mevcut servisleri yeniden kullan.
3. Önce architecture/interface planını çıkar.
4. Component boundaries netleşmeden büyük kod yazma.
5. Mevcut safety invariants'ı testlerle kilitle.
6. Paralel sub-agent kullanırken aynı dosyalarda eşzamanlı edit yaptırma.
7. Her milestone sonunda focused tests + full suite + compile checks çalıştır.
8. `PROGRESS.md` güncel tutulmalı.
9. AI-Assistant, başka repo main branch'i ve production/VPS'e dokunma.
10. UI polish yerine ilk olarak çalışan end-to-end control workflow'u teslim et.
