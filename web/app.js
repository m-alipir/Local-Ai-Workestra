const PLAN_STORAGE_KEY = "workestra.plans";
const SELECTED_PLAN_STORAGE_KEY = "workestra.selected-plans";
const state = { projectId: null, planId: null, runId: null, currentTaskId: null, lastEventId: 0, projects: [], projectEditMode: false, projectEditOriginal: null, selectedRunToken: 0, eventSource: null };
const $ = (id) => document.getElementById(id);

function readStorage(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key) || "null") ?? fallback; }
  catch (_) { return fallback; }
}

function writeStorage(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); }
  catch (_) { /* Storage is optional; the server remains authoritative. */ }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
  } catch (cause) {
    const error = new Error("Control service is unreachable.");
    error.details = { path, cause: String(cause) };
    throw error;
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.error?.message || body.message || `Request failed (${response.status})`);
    error.details = { status: response.status, path, body };
    throw error;
  }
  clearError();
  return body;
}

function clearError() { $("error-banner").hidden = true; }

function showError(error) {
  $("error-summary").textContent = error instanceof Error ? error.message : String(error);
  $("error-details").textContent = error?.details
    ? JSON.stringify(error.details, null, 2)
    : String(error?.stack || error);
  $("error-banner").hidden = false;
}

function parseVerifierArgv(value) {
  const argv = JSON.parse(value);
  if (!Array.isArray(argv) || argv.some((item) => typeof item !== "string" || !item)) {
    throw new Error("Verifier argv must be a JSON array of non-empty strings.");
  }
  return argv;
}

function setStatus(id, value, status = "unknown") {
  const element = $(id);
  element.textContent = value;
  element.dataset.status = status;
  if (id === "health") {
    const dot = document.querySelector(".health-dot");
    if (dot) dot.dataset.status = status;
  }
}

function textElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderPlanPreview(plan) {
  const preview = $("plan-preview");
  preview.replaceChildren();
  const raw = plan && typeof plan === "object" ? plan : { value: plan };
  const compiledPlan = raw.plan && typeof raw.plan === "object" ? raw.plan : raw;
  const tasks = Array.isArray(compiledPlan.tasks) ? compiledPlan.tasks : [];
  const summary = textElement("div", "preview-summary");
  const stats = [
    [String(tasks.length), "tasks"],
    [tasks.filter((task) => task.requires_approval).length.toString(), "approval gates"],
    [tasks.filter((task) => ["high", "critical"].includes(task.risk)).length.toString(), "high-risk"],
  ];
  for (const [value, label] of stats) {
    const stat = textElement("div", "preview-stat");
    stat.append(textElement("strong", "", value), textElement("span", "", label));
    summary.append(stat);
  }
  preview.append(summary);
  if (compiledPlan.request) preview.append(textElement("p", "preview-request", compiledPlan.request));
  const taskList = textElement("div", "preview-tasks");
  tasks.forEach((task, index) => {
    const item = textElement("div", "preview-task");
    const copy = textElement("div", "preview-task-copy");
    copy.append(
      textElement("strong", "", task.description || task.id || `Task ${index + 1}`),
      textElement("span", "", [task.kind, task.risk, task.requires_approval ? "approval required" : "no approval"].filter(Boolean).join(" · ")),
    );
    item.append(textElement("span", "preview-task-index", String(index + 1).padStart(2, "0")), copy);
    taskList.append(item);
  });
  if (tasks.length) preview.append(taskList);
  const rawDetails = document.createElement("details");
  rawDetails.className = "raw-fallback";
  rawDetails.append(textElement("summary", "", "Raw compiled plan"));
  rawDetails.append(textElement("pre", "output", JSON.stringify(raw, null, 2)));
  preview.append(rawDetails);
}

function renderRunList(items) {
  const list = $("run-list");
  list.replaceChildren();
  if (!items.length) {
    list.append(textElement("p", "empty-state", "No runs."));
    return;
  }
  for (const run of items) {
    const runId = run.run_id || run.id;
    const status = run.status || "unknown";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "run-list-item";
    button.dataset.runId = runId;
    button.dataset.status = status;
    button.setAttribute("aria-current", runId === state.runId ? "true" : "false");
    button.append(
      textElement("span", "run-list-title", run.request || runId),
      (() => {
        const meta = textElement("span", "run-list-meta");
        meta.append(textElement("span", "", runId), textElement("span", "", status.replaceAll("_", " ")));
        return meta;
      })(),
    );
    button.onclick = () => selectRun(runId);
    list.append(button);
  }
}

function syncRunListSelection() {
  for (const button of document.querySelectorAll("#run-list .run-list-item")) {
    button.setAttribute("aria-current", button.dataset.runId === state.runId ? "true" : "false");
  }
}

function renderTask(task, index) {
  const status = task.status || "pending";
  const item = textElement("article", "task");
  item.dataset.status = status;
  item.setAttribute("role", "listitem");
  const header = textElement("div", "task-header");
  header.append(
    textElement("strong", "task-title", `${task.id || `Task ${index + 1}`} · ${task.description || "Untitled task"}`),
    textElement("span", "badge", status.replaceAll("_", " ")),
  );
  header.lastChild.dataset.status = status;
  item.append(header);
  if (task.error) item.append(textElement("p", "task-copy", task.error));
  const meta = [
    task.kind,
    task.attempts ? `${task.attempts} attempt${task.attempts === 1 ? "" : "s"}` : null,
    task.approval_granted ? "approval granted" : (status === "waiting_for_approval" ? "approval required" : null),
    task.verification_status && task.verification_status !== "not_requested" ? task.verification_status.replaceAll("_", " ") : null,
  ].filter(Boolean);
  if (meta.length) item.append(textElement("div", "task-meta", meta.join(" · ")));
  return item;
}

function renderTaskList(tasks) {
  const list = $("task-list");
  list.replaceChildren();
  if (!tasks.length) list.append(textElement("p", "empty-state", "No tasks recorded for this run."));
  else tasks.forEach((task, index) => list.append(renderTask(task, index)));
}

function eventsQuery(projectId, lastEventId = 0) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (lastEventId > 0) params.set("last_event_id", String(lastEventId));
  const query = params.toString();
  return query ? `?${query}` : "";
}

function lastEventIdFromStream(stream) {
  return [...stream.matchAll(/^id:\s*(\d+)\s*$/gm)]
    .map((match) => Number(match[1]))
    .filter(Number.isSafeInteger)
    .pop() || 0;
}

function selectedProject() { return $("project-select").value || state.projectId; }

function selectedProjectRecord() {
  return state.projects.find((project) => project.id === selectedProject()) || null;
}

function syncProjectActions() {
  const disabled = !selectedProjectRecord();
  $("edit-project").disabled = disabled;
  $("delete-project").disabled = disabled;
}

function syncRunActions() {
  const hasRun = Boolean(state.runId);
  const status = $("run-status").textContent;
  const terminal = ["passed", "failed", "skipped"].includes(status);
  const waitingForApproval = status === "waiting_for_approval";
  $("resume-run").textContent = waitingForApproval ? "Approve & resume" : "Resume";
  $("resume-run").setAttribute("aria-label", waitingForApproval ? "Approve current task and resume run" : "Resume run");
  $("resume-run").disabled = !hasRun || !waitingForApproval;
  // The synchronous engine has no safe pause/cancel primitive yet.
  $("pause-run").disabled = true;
  $("cancel-run").disabled = true;
  $("archive-run").disabled = !hasRun || !terminal;
  $("cleanup-run").disabled = !hasRun || !terminal;
}

function storedPlans() {
  const plans = readStorage(PLAN_STORAGE_KEY, []);
  return Array.isArray(plans) ? plans : [];
}

function plansForProject(projectId) {
  return storedPlans().filter((plan) => plan.project_id === projectId);
}

function selectedPlanId(projectId) {
  const selected = readStorage(SELECTED_PLAN_STORAGE_KEY, {});
  return selected && typeof selected === "object" ? selected[projectId] : null;
}

function saveSelectedPlan(projectId, planId) {
  const selected = readStorage(SELECTED_PLAN_STORAGE_KEY, {});
  if (selected && typeof selected === "object") {
    selected[projectId] = planId;
    writeStorage(SELECTED_PLAN_STORAGE_KEY, selected);
  }
}

function renderPlanHistory() {
  const select = $("plan-history");
  const plans = plansForProject(state.projectId);
  select.replaceChildren();
  if (!plans.length) {
    select.add(new Option("No saved plans", ""));
    $("reuse-plan").disabled = true;
    setStatus("plan-status", "No plan selected", "idle");
    return;
  }
  for (const plan of plans) {
    const title = plan.title || plan.markdown?.split("\n").find((line) => line.trim()) || "Untitled plan";
    const when = plan.created_at ? new Date(plan.created_at).toLocaleString() : (plan.status || "saved");
    select.add(new Option(`${title} · ${when}`, plan.id));
  }
  const preferred = selectedPlanId(state.projectId);
  select.value = plans.some((plan) => plan.id === preferred) ? preferred : plans[0].id;
  state.planId = select.value;
  $("reuse-plan").disabled = false;
  setStatus("plan-status", "Saved plan selected", "saved");
}

function rememberPlan(record) {
  const plans = [record, ...storedPlans().filter((plan) => plan.id !== record.id)].slice(0, 30);
  writeStorage(PLAN_STORAGE_KEY, plans);
  saveSelectedPlan(record.project_id, record.id);
  renderPlanHistory();
}

async function refreshPlans() {
  if (!state.projectId) { renderPlanHistory(); return; }
  const response = await request(`/plans?project_id=${encodeURIComponent(state.projectId)}`);
  const plans = Array.isArray(response.data || response) ? (response.data || response) : [];
  writeStorage(PLAN_STORAGE_KEY, plans);
  renderPlanHistory();
  const preferred = selectedPlanId(state.projectId);
  if (preferred && plans.some((plan) => plan.id === preferred)) await reusePlan(preferred);
}

async function refreshProjects() {
  const projects = await request("/projects");
  const items = projects.data || projects;
  state.projects = Array.isArray(items) ? items : [];
  const select = $("project-select");
  const options = state.projects.map((project) => {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = `${project.name} — ${project.workspace_root || project.path}`;
    return option;
  });
  if (!options.length) {
    const option = new Option("No projects available", "");
    option.disabled = true;
    options.push(option);
  }
  select.replaceChildren(...options);
  if (state.projectId && state.projects.some((project) => project.id === state.projectId)) select.value = state.projectId;
  state.projectId = select.value || null;
  state.planId = selectedPlanId(state.projectId);
  const project = state.projects.find((item) => item.id === state.projectId);
  $("project-detail").textContent = project ? (project.workspace_root || project.path || "Path unavailable") : "No project selected.";
  syncProjectActions();
  await refreshPlans();
}

function clearRunDetail() {
  if (state.eventSource) state.eventSource.close();
  state.eventSource = null;
  state.runId = null;
  state.currentTaskId = null;
  state.lastEventId = 0;
  syncRunListSelection();
  $("run-detail").hidden = true;
  $("run-heading").textContent = "";
  setStatus("run-status", "", "unknown");
  $("task-list").replaceChildren();
  $("timeline").textContent = "";
  $("run-artifacts").textContent = "";
  clearDiagnostics();
  syncRunActions();
}

function clearDiagnostics() {
  $("diagnostics").hidden = true;
  $("diagnostic-summary").textContent = "";
  $("diagnostic-details").textContent = "";
}

function invalidateRunSelection() {
  state.selectedRunToken += 1;
  clearRunDetail();
}

function isCurrentRun(runId, token) {
  return state.runId === runId && state.selectedRunToken === token;
}

async function refreshRuns(token = state.selectedRunToken) {
  const projectId = selectedProject();
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  let runs;
  try {
    runs = await request(`/runs${query}`);
  } catch (error) {
    if (token === state.selectedRunToken) showError(error);
    return;
  }
  if (token !== state.selectedRunToken) return;
  const items = Array.isArray(runs.data || runs) ? (runs.data || runs) : [];
  renderRunList(items);
  const selected = items.find((run) => (run.run_id || run.id) === state.runId);
  if (selected && token === state.selectedRunToken) {
    state.currentTaskId = selected.current_task || null;
    setStatus("run-status", selected.status || "unknown", selected.status || "unknown");
    if (["pending", "running", "waiting_for_approval"].includes(selected.status)) clearDiagnostics();
    syncRunActions();
  }
}

async function selectRun(runId) {
  const token = ++state.selectedRunToken;
  clearRunDetail();
  state.runId = runId;
  syncRunListSelection();
  try {
    const projectId = selectedProject();
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
    const run = await request(`/runs/${encodeURIComponent(runId)}${query}`);
    if (!isCurrentRun(runId, token)) return;
    $("run-detail").hidden = false;
    $("run-heading").textContent = `Run ${run.run_id || run.id}`;
    state.currentTaskId = run.current_task || null;
    setStatus("run-status", run.status || "unknown", run.status || "unknown");
    syncRunActions();
    renderTaskList(Array.isArray(run.tasks) ? run.tasks : []);
    const eventsResponse = await fetch(`/api/runs/${encodeURIComponent(runId)}/events${eventsQuery(projectId, state.lastEventId)}`);
    if (!eventsResponse.ok) throw new Error(`Unable to load run events (${eventsResponse.status})`);
    const timeline = await eventsResponse.text();
    if (!isCurrentRun(runId, token)) return;
    state.lastEventId = lastEventIdFromStream(timeline);
    $("timeline").textContent = timeline;
    const artifacts = await request(`/runs/${encodeURIComponent(runId)}/artifacts${query}`);
    if (!isCurrentRun(runId, token)) return;
    const diff = await request(`/runs/${encodeURIComponent(runId)}/diff${query}`);
    if (!isCurrentRun(runId, token)) return;
    $("run-artifacts").textContent = `${JSON.stringify(artifacts, null, 2)}\n\n${diff.content || "No committed diff recorded."}`;
    const diagnostics = await request(`/runs/${encodeURIComponent(runId)}/diagnostics${query}`).catch((error) => ({ summary: error.message, source_errors: [error.message] }));
    if (!isCurrentRun(runId, token)) return;
    renderDiagnostics(diagnostics, run, $("timeline").textContent, artifacts, diff);
    connectEvents(runId, token);
  } catch (error) {
    if (isCurrentRun(runId, token)) showError(error);
  }
}

function renderDiagnostics(diagnostics, run, events, artifacts, diff) {
  const failures = (run.tasks || []).filter((task) => task.error || ["failed", "blocked"].includes(task.status));
  const failed = run.status === "failed" && (failures.length > 0 || (diagnostics.failure_class && diagnostics.failure_class !== "none"));
  $("diagnostics").hidden = !failed;
  if (!failed) return;
  $("diagnostic-summary").textContent = diagnostics.summary || failures.map((task) => `${task.id}: ${task.error || task.status}`).join("\n") || `Run ${run.status || "failed"}.`;
  $("diagnostic-details").textContent = JSON.stringify(diagnostics, null, 2);
}

function closeProjectEditor() {
  $("project-edit-form").hidden = true;
  state.projectEditMode = false;
  state.projectEditOriginal = null;
}

function projectEditValues(project) {
  return {
    name: project.name || "",
    path: project.workspace_root || project.path || "",
    test_argv: Array.isArray(project.test_command)
      ? [...project.test_command]
      : (Array.isArray(project.test_argv) ? [...project.test_argv] : []),
  };
}

function openProjectEditor() {
  const project = selectedProjectRecord();
  if (!project) return;
  const values = projectEditValues(project);
  state.projectEditMode = true;
  state.projectEditOriginal = values;
  $("project-edit-name").value = values.name;
  $("project-edit-path").value = values.path;
  $("project-edit-test-argv").value = JSON.stringify(values.test_argv);
  $("project-edit-form").hidden = false;
  $("project-edit-name").focus();
}

function projectEditPayload(project) {
  const current = {
    name: $("project-edit-name").value,
    path: $("project-edit-path").value,
    test_argv: parseVerifierArgv($("project-edit-test-argv").value),
  };
  const original = state.projectEditOriginal || projectEditValues(project);
  return Object.fromEntries(
    Object.entries(current).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(original[key])),
  );
}

async function deleteSelectedProject() {
  const project = selectedProjectRecord();
  if (!project) return;
  if (!window.confirm(`Delete project “${project.name}”? Plans and local history will be kept.`)) return;
  const projectId = project.id;
  try {
    await request(`/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
    closeProjectEditor();
    if (state.projectId === projectId) {
      state.projectId = null;
      state.planId = null;
      invalidateRunSelection();
    }
    await refreshProjects();
    await refreshRuns();
  } catch (error) {
    showError(error);
  }
}

async function manageRun(action, label) {
  const runId = state.runId;
  const projectId = selectedProject();
  if (!runId || !window.confirm(`${label} run ${runId}?`)) return;
  try {
    await request(`/runs/${encodeURIComponent(runId)}/${action}`, {
      method: "POST",
      body: JSON.stringify({ project_id: projectId }),
    });
    if (state.runId === runId) invalidateRunSelection();
    await refreshRuns();
  } catch (error) {
    showError(error);
  }
}

async function reusePlan(planId = $("plan-history").value) {
  const record = plansForProject(state.projectId).find((plan) => plan.id === planId);
  if (!record) return;
  state.planId = record.id;
  saveSelectedPlan(state.projectId, record.id);
  $("plan-markdown").value = record.markdown;
  setStatus("plan-status", "Loading saved plan", "loading");
  try {
    const plan = await request(`/plans/${encodeURIComponent(record.id)}`);
    renderPlanPreview(plan);
    $("start-run").disabled = !plan.compiled;
    setStatus("plan-status", plan.compiled ? "Compiled plan ready" : "Saved draft", plan.compiled ? "compiled" : "draft");
  } catch (error) {
    $("start-run").disabled = true;
    setStatus("plan-status", "Unable to load plan", "error");
    showError(error);
  }
}

async function compilePlan(planId) {
  const compiled = await request(`/plans/${encodeURIComponent(planId)}/compile`, { method: "POST" });
  renderPlanPreview(compiled);
  $("start-run").disabled = compiled.status !== "compiled" || Boolean(compiled.error);
  setStatus("plan-status", compiled.status === "compiled" ? "Compiled plan ready" : "Compilation failed", compiled.status === "compiled" ? "compiled" : "error");
  const saved = await request(`/plans/${encodeURIComponent(planId)}`);
  rememberPlan(saved);
}

function connectEvents(runId, token = state.selectedRunToken) {
  if (!isCurrentRun(runId, token)) return;
  if (state.eventSource) state.eventSource.close();
  const projectId = selectedProject();
  const query = eventsQuery(projectId, state.lastEventId);
  const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events${query}`);
  state.eventSource = source;
  const applyEvent = (event) => {
    if (!isCurrentRun(runId, token) || state.eventSource !== source) return;
    const eventId = Number(event.lastEventId);
    if (Number.isSafeInteger(eventId) && eventId > 0) {
      if (eventId <= state.lastEventId) return;
      state.lastEventId = eventId;
    }
    let payload;
    try { payload = JSON.parse(event.data); } catch (_) { /* Keep plain-text event streams usable. */ }
    if (payload?.run_id && payload.run_id !== runId) return;
    const current = $("timeline").textContent;
    $("timeline").textContent = `${current}\n${event.data}`.trim();
    refreshRuns(token).catch((error) => { if (isCurrentRun(runId, token)) showError(error); });
  };
  source.onmessage = applyEvent;
  for (const name of ["approval_granted", "approval_requested", "checkpoint_created", "checkpoint_failed", "coding_output_rejected", "model_attempt_started", "task_started", "task_completed", "tests_finished", "verification_baseline_failed", "verification_bootstrapped", "verification_compared"]) {
    source.addEventListener(name, applyEvent);
  }
  source.onerror = () => {
    if (!isCurrentRun(runId, token) || state.eventSource !== source) { source.close(); return; }
    source.close();
    state.eventSource = null;
    setTimeout(() => {
      if (isCurrentRun(runId, token) && state.eventSource === null) connectEvents(runId, token);
    }, 1500);
  };
}

$("project-select").onchange = () => { invalidateRunSelection(); state.projectId = selectedProject(); state.planId = null; syncProjectActions(); refreshProjects().then(refreshRuns).catch(showError); };
$("refresh-projects").onclick = () => refreshProjects().catch(showError);
$("refresh-runs").onclick = () => refreshRuns().catch(showError);
$("edit-project").onclick = openProjectEditor;
$("cancel-project-edit").onclick = closeProjectEditor;
$("project-edit-form").onsubmit = async (event) => {
  event.preventDefault();
  const projectId = selectedProject();
  if (!projectId || !state.projectEditMode) return;
  try {
    const project = selectedProjectRecord();
    if (!project) return;
    const payload = projectEditPayload(project);
    if (!Object.keys(payload).length) {
      closeProjectEditor();
      return;
    }
    await request(`/projects/${encodeURIComponent(projectId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    closeProjectEditor();
    await refreshProjects();
    await refreshRuns();
  } catch (error) {
    showError(error);
  }
};
$("delete-project").onclick = deleteSelectedProject;
$("plan-history").onchange = () => reusePlan().catch(showError);
$("reuse-plan").onclick = () => reusePlan().catch(showError);
$("project-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const testArgv = parseVerifierArgv($("project-test-argv").value);
    await request("/projects", { method: "POST", body: JSON.stringify({ name: $("project-name").value, path: $("project-path").value, test_argv: testArgv }) });
    event.target.reset(); await refreshProjects();
  } catch (error) { showError(error); }
};
$("plan-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const markdown = $("plan-markdown").value;
    const imported = await request("/plans/import", { method: "POST", body: JSON.stringify({ project_id: selectedProject(), markdown }) });
    state.planId = imported.id || imported.plan_id;
    rememberPlan({ id: state.planId, project_id: selectedProject(), title: markdown.split("\n").find((line) => line.trim()) || "Untitled plan", markdown, created_at: new Date().toISOString() });
    await compilePlan(state.planId);
  } catch (error) { showError(error); }
};
$("start-run").onclick = async () => {
  try {
    invalidateRunSelection();
    const run = await request("/runs", { method: "POST", body: JSON.stringify({ project_id: selectedProject(), plan_id: state.planId }) });
    const runId = run.run_id || run.id;
    await refreshRuns();
    if (runId) { state.runId = runId; await selectRun(runId); }
  }
  catch (error) { showError(error); }
};
async function resumeSelectedRun() {
  const runId = state.runId;
  const token = state.selectedRunToken;
  const projectId = selectedProject();
  const waitingForApproval = $("run-status").textContent === "waiting_for_approval";
  if (!runId || !isCurrentRun(runId, token)) return;
  try {
    if (waitingForApproval) {
      if (!state.currentTaskId) throw new Error("This run is waiting for approval but has no current task.");
      await request(`/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(state.currentTaskId)}/approve`, {
        method: "POST",
        body: JSON.stringify({ project_id: projectId }),
      });
    }
    if (!isCurrentRun(runId, token)) return;
    await request(`/runs/${encodeURIComponent(runId)}/resume`, {
      method: "POST",
      body: JSON.stringify({ project_id: projectId }),
    });
    if (isCurrentRun(runId, token)) await selectRun(runId);
  } catch (error) {
    if (isCurrentRun(runId, token)) showError(error);
  }
}

$("resume-run").onclick = resumeSelectedRun;
for (const [id, action] of [["pause-run", "pause"], ["cancel-run", "cancel"]]) {
  $(id).onclick = () => state.runId && request(`/runs/${encodeURIComponent(state.runId)}/${action}`, { method: "POST" }).then(() => selectRun(state.runId)).catch(showError);
}
$("archive-run").onclick = () => manageRun("archive", "Archive");
$("cleanup-run").onclick = () => manageRun("cleanup", "Clean up");

async function refreshHealth() {
  try {
    const response = await request("/health");
    const healthy = response?.status === "ok";
    setStatus("health", healthy ? "Control plane online" : "Control plane degraded", healthy ? "ok" : "error");
  } catch (error) {
    setStatus("health", "Control plane offline", "error");
    showError(error);
  }
}

Promise.all([refreshHealth(), refreshProjects()]).then(() => refreshRuns()).catch(showError);
