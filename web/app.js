const state = { projectId: null, planId: null, runId: null, eventSource: null };
const $ = (id) => document.getElementById(id);

async function request(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error?.message || body.message || `Request failed (${response.status})`);
  return body;
}

function showError(error) { window.alert(error instanceof Error ? error.message : String(error)); }

function selectedProject() { return $("project-select").value || state.projectId; }

async function refreshProjects() {
  const projects = await request("/projects");
  const select = $("project-select");
  select.replaceChildren(...(projects.data || projects).map((project) => {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = `${project.name} — ${project.workspace_root || project.path}`;
    return option;
  }));
  state.projectId = select.value || null;
  const project = (projects.data || projects).find((item) => item.id === state.projectId);
  $("project-detail").textContent = project ? (project.workspace_root || project.path || "Path unavailable") : "No project selected.";
}

async function refreshRuns() {
  const runs = await request("/runs");
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
  const run = await request(`/runs/${encodeURIComponent(runId)}`);
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
  $("timeline").textContent = await eventsResponse.text();
  const artifacts = await request(`/runs/${encodeURIComponent(runId)}/artifacts`).catch(() => ({}));
  const diff = await request(`/runs/${encodeURIComponent(runId)}/diff`).catch(() => ({}));
  $("run-artifacts").textContent = `${JSON.stringify(artifacts, null, 2)}\n\n${diff.content || "No committed diff recorded."}`;
  connectEvents(runId);
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

$("project-select").onchange = () => { state.projectId = selectedProject(); refreshProjects().catch(showError); };
$("refresh-projects").onclick = () => refreshProjects().catch(showError);
$("refresh-runs").onclick = () => refreshRuns().catch(showError);
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
    const imported = await request("/plans/import", { method: "POST", body: JSON.stringify({ project_id: selectedProject(), markdown: $("plan-markdown").value }) });
    state.planId = imported.id || imported.plan_id;
    const compiled = await request(`/plans/${encodeURIComponent(state.planId)}/compile`, { method: "POST" });
    $("plan-preview").textContent = JSON.stringify(compiled, null, 2);
    $("start-run").disabled = compiled.status !== "compiled" || Boolean(compiled.error);
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
Promise.all([refreshProjects(), refreshRuns()]).catch(showError);
