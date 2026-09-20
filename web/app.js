const PLAN_STORAGE_KEY = "workestra.plans";
const SELECTED_PLAN_STORAGE_KEY = "workestra.selected-plans";
const state = { projectId: null, planId: null, runId: null, eventSource: null };
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

function selectedProject() { return $("project-select").value || state.projectId; }

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
    $("plan-status").textContent = "No plan selected";
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
  $("plan-status").textContent = "Saved plan selected";
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
  const plans = response.data || response;
  writeStorage(PLAN_STORAGE_KEY, Array.isArray(plans) ? plans : []);
  renderPlanHistory();
  const preferred = selectedPlanId(state.projectId);
  if (preferred && plans.some((plan) => plan.id === preferred)) await reusePlan(preferred);
}

async function refreshProjects() {
  const projects = await request("/projects");
  const items = projects.data || projects;
  const select = $("project-select");
  select.replaceChildren(...items.map((project) => {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = `${project.name} — ${project.workspace_root || project.path}`;
    return option;
  }));
  if (state.projectId && items.some((project) => project.id === state.projectId)) select.value = state.projectId;
  state.projectId = select.value || null;
  state.planId = selectedPlanId(state.projectId);
  const project = items.find((item) => item.id === state.projectId);
  $("project-detail").textContent = project ? (project.workspace_root || project.path || "Path unavailable") : "No project selected.";
  await refreshPlans();
}

async function refreshRuns() {
  const projectId = selectedProject();
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const runs = await request(`/runs${query}`);
  const list = $("run-list");
  const items = runs.data || runs;
  list.replaceChildren(...(items.length ? items.map((run) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${run.run_id || run.id} · ${run.status || "unknown"}`;
    button.onclick = () => selectRun(run.run_id || run.id);
    return button;
  }) : [Object.assign(document.createElement("p"), { textContent: "No runs." })]));
}

async function selectRun(runId) {
  state.runId = runId;
  const projectId = selectedProject();
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const run = await request(`/runs/${encodeURIComponent(runId)}${query}`);
  $("run-detail").hidden = false;
  $("run-heading").textContent = `Run ${run.run_id || run.id}`;
  $("run-status").textContent = run.status || "unknown";
  $("task-list").replaceChildren(...(run.tasks || []).map((task) => {
    const item = document.createElement("div");
    item.className = "task";
    item.textContent = `${task.id}: ${task.status} — ${task.description}`;
    return item;
  }));
  const eventsResponse = await fetch(`/api/runs/${encodeURIComponent(runId)}/events`);
  if (!eventsResponse.ok) throw new Error(`Unable to load run events (${eventsResponse.status})`);
  $("timeline").textContent = await eventsResponse.text();
  const artifacts = await request(`/runs/${encodeURIComponent(runId)}/artifacts${query}`);
  const diff = await request(`/runs/${encodeURIComponent(runId)}/diff${query}`);
  $("run-artifacts").textContent = `${JSON.stringify(artifacts, null, 2)}\n\n${diff.content || "No committed diff recorded."}`;
  const diagnostics = await request(`/runs/${encodeURIComponent(runId)}/diagnostics${query}`).catch((error) => ({ summary: error.message, source_errors: [error.message] }));
  renderDiagnostics(diagnostics, run, $("timeline").textContent, artifacts, diff);
  connectEvents(runId);
}

function renderDiagnostics(diagnostics, run, events, artifacts, diff) {
  const failures = (run.tasks || []).filter((task) => task.error || ["failed", "blocked"].includes(task.status));
  const failed = run.status === "failed" || failures.length > 0 || (diagnostics.failure_class && diagnostics.failure_class !== "none");
  $("diagnostics").hidden = !failed;
  if (!failed) return;
  $("diagnostic-summary").textContent = diagnostics.summary || failures.map((task) => `${task.id}: ${task.error || task.status}`).join("\n") || `Run ${run.status || "failed"}.`;
  $("diagnostic-details").textContent = JSON.stringify(diagnostics, null, 2);
}

async function reusePlan(planId = $("plan-history").value) {
  const record = plansForProject(state.projectId).find((plan) => plan.id === planId);
  if (!record) return;
  state.planId = record.id;
  saveSelectedPlan(state.projectId, record.id);
  $("plan-markdown").value = record.markdown;
  $("plan-status").textContent = "Loading saved plan";
  try {
    const plan = await request(`/plans/${encodeURIComponent(record.id)}`);
    $("plan-preview").textContent = JSON.stringify(plan, null, 2);
    $("start-run").disabled = !plan.compiled;
    $("plan-status").textContent = plan.compiled ? "Compiled plan ready" : "Saved draft";
  } catch (error) {
    $("start-run").disabled = true;
    showError(error);
  }
}

async function compilePlan(planId) {
  const compiled = await request(`/plans/${encodeURIComponent(planId)}/compile`, { method: "POST" });
  $("plan-preview").textContent = JSON.stringify(compiled, null, 2);
  $("start-run").disabled = compiled.status !== "compiled" || Boolean(compiled.error);
  $("plan-status").textContent = compiled.status === "compiled" ? "Compiled plan ready" : "Compilation failed";
  const saved = await request(`/plans/${encodeURIComponent(planId)}`);
  rememberPlan(saved);
}

function connectEvents(runId) {
  if (state.eventSource) state.eventSource.close();
  state.eventSource = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
  state.eventSource.onmessage = (event) => {
    const current = $("timeline").textContent;
    $("timeline").textContent = `${current}\n${event.data}`.trim();
    refreshRuns().catch(showError);
  };
  state.eventSource.onerror = () => { state.eventSource?.close(); setTimeout(() => state.runId === runId && connectEvents(runId), 1500); };
}

$("project-select").onchange = () => { state.projectId = selectedProject(); state.planId = null; refreshProjects().then(refreshRuns).catch(showError); };
$("refresh-projects").onclick = () => refreshProjects().catch(showError);
$("refresh-runs").onclick = () => refreshRuns().catch(showError);
$("plan-history").onchange = () => reusePlan().catch(showError);
$("reuse-plan").onclick = () => reusePlan().catch(showError);
$("project-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const testArgv = JSON.parse($("project-test-argv").value);
    if (!Array.isArray(testArgv) || testArgv.some((item) => typeof item !== "string" || !item)) throw new Error("Verifier argv must be a JSON array of non-empty strings.");
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
    const run = await request("/runs", { method: "POST", body: JSON.stringify({ project_id: selectedProject(), plan_id: state.planId }) });
    const runId = run.run_id || run.id;
    await refreshRuns();
    if (runId) { state.runId = runId; await selectRun(runId); }
  }
  catch (error) { showError(error); }
};
for (const [id, action] of [["resume-run", "resume"], ["pause-run", "pause"], ["cancel-run", "cancel"]]) {
  $(id).onclick = () => state.runId && request(`/runs/${encodeURIComponent(state.runId)}/${action}`, { method: "POST" }).then(() => selectRun(state.runId)).catch(showError);
}
$("health").textContent = "Ready";
refreshProjects().then(refreshRuns).catch(showError);
