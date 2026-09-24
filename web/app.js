const PLAN_STORAGE_KEY = "workestra.plans";
const SELECTED_PLAN_STORAGE_KEY = "workestra.selected-plans";
const SELECTED_SOURCE_STORAGE_KEY = "workestra.selected-source-plan";
const state = {
  projectId: null,
  planId: null,
  compiledPlanId: null,
  compiledPlanRevision: null,
  compiledPlanProjectId: null,
  compiledProjectSpec: null,
  projectCreationEligible: false,
  currentTaskId: null,
  lastEventId: 0,
  projects: [],
  planGroups: [],
  runs: [],
  projectEditMode: false,
  projectEditOriginal: null,
  selectedRunToken: 0,
  runRefreshGeneration: 0,
  compileGeneration: 0,
  planLoadGeneration: 0,
  eventSource: null,
  runTimer: null,
  activeRun: null,
  workbench: "plan",
};
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

function formatElapsed(seconds) {
  const wholeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(wholeSeconds / 60);
  return minutes ? `${minutes}m ${String(wholeSeconds % 60).padStart(2, "0")}s` : `${wholeSeconds}s`;
}

function formatDuration(run) {
  const start = Date.parse(run?.created_at || "");
  const terminal = ["passed", "failed", "skipped", "completed"].includes(run?.status);
  const end = terminal ? Date.parse(run?.updated_at || "") : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "—";
  return formatElapsed((end - start) / 1000);
}

function stopRunTimer() {
  if (state.runTimer) clearInterval(state.runTimer);
  state.runTimer = null;
}

function updateActiveRunDuration() {
  if (state.activeRun) $("active-run-duration").textContent = formatDuration(state.activeRun);
}

function compiledPlanIdentity(plan) {
  const raw = plan && typeof plan === "object" ? plan : {};
  const nested = raw.plan && typeof raw.plan === "object" ? raw.plan : {};
  const value = (keys) => keys.map((key) => raw[key] ?? nested[key]).find((item) => item !== undefined && item !== null && item !== "");
  const id = value(["compiled_revision", "compiled_revision_id", "plan_revision_id", "revision_id", "compiled_plan_revision", "generation_id", "generation"]);
  const digest = value(["compiled_digest", "compiled_plan_digest", "plan_digest", "content_digest", "digest", "sha256"]);
  const compiledAt = value(["compiled_at"]);
  return { id: id == null ? null : String(id), digest: digest == null ? null : String(digest), compiledAt: compiledAt == null ? null : String(compiledAt) };
}

function planRevisionLabel(identity) {
  if (!identity?.id && !identity?.digest) return "Revision unavailable";
  const parts = [identity.id ? `Revision ${identity.id}` : null, identity.digest ? `digest ${identity.digest.slice(0, 12)}` : null, identity.compiledAt ? new Date(identity.compiledAt).toLocaleString() : null];
  return parts.filter(Boolean).join(" · ");
}

function taskProgress(run) {
  const tasks = Array.isArray(run?.tasks) ? run.tasks : [];
  if (!tasks.length) return "0/0";
  const done = tasks.filter((task) => ["passed", "completed", "skipped"].includes(task.status)).length;
  return `${done}/${tasks.length}`;
}

function failureClass(run) {
  if (run?.status !== "failed") return "";
  const failedTask = (run.tasks || []).find((task) => task.status === "failed" || task.status === "blocked");
  return failedTask?.verification_status === "failed" ? "verification failure" : "task failure";
}

function renderActiveRun(run) {
  stopRunTimer();
  state.activeRun = run || null;
  const hasRun = Boolean(run);
  $("active-run-title").textContent = hasRun ? `Run ${run.run_id || run.id}` : "No active run";
  setStatus("active-run-status", hasRun ? (run.status || "unknown").replaceAll("_", " ") : "Idle", hasRun ? (run.status || "unknown") : "idle");
  $("active-run-request").textContent = hasRun ? (run.request || "Untitled run") : "Start or select a run to keep its progress in view.";
  $("active-run-progress").textContent = hasRun ? taskProgress(run) : "—";
  $("active-run-duration").textContent = hasRun ? formatDuration(run) : "—";
  $("active-run-task").textContent = hasRun ? (run.current_task || "Complete") : "—";
  $("active-run-meta").textContent = hasRun
    ? [run.status === "failed" ? failureClass(run) : null, run.updated_at ? new Date(run.updated_at).toLocaleString() : null].filter(Boolean).join(" · ")
    : "The selected project has no run in focus.";
  $("active-run-open").disabled = !hasRun;
  $("active-run-open").dataset.runId = hasRun ? (run.run_id || run.id) : "";
  if (hasRun) {
    updateActiveRunDuration();
    if (!["passed", "failed", "skipped", "completed"].includes(run.status)) state.runTimer = setInterval(updateActiveRunDuration, 1000);
  }
}

function switchWorkbench(name) {
  const next = ["plan", "run", "history"].includes(name) ? name : "plan";
  state.workbench = next;
  for (const tab of document.querySelectorAll("[data-workbench-tab]")) {
    const active = tab.dataset.workbenchTab === next;
    tab.setAttribute("aria-selected", String(active));
  }
  for (const panel of document.querySelectorAll(".workbench-panel")) {
    panel.hidden = panel.id !== `${next}-workbench`;
  }
}

function renderPlanPreview(plan) {
  const preview = $("plan-preview");
  preview.replaceChildren();
  const raw = plan && typeof plan === "object" ? plan : { value: plan };
  const identity = compiledPlanIdentity(raw);
  $("plan-revision").textContent = planRevisionLabel(identity);
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
  const projectSpec = raw.project_spec && typeof raw.project_spec === "object" ? raw.project_spec : null;
  if (projectSpec) {
    const project = textElement("section", "preview-project");
    project.append(textElement("h4", "", "Project specification"));
    const research = Array.isArray(projectSpec.research_requirements) ? projectSpec.research_requirements : [];
    const details = [
      ["Name", projectSpec.name],
      ["Intent", projectSpec.intent],
      ["Workspace", projectSpec.workspace_root],
      ["Stack", [projectSpec.language, projectSpec.framework || projectSpec.engine].filter(Boolean).join(" · ")],
      ["Bootstrap", projectSpec.bootstrap_profile ? `${projectSpec.bootstrap_profile} · trusted Workestra setup` : (research.length ? "Research required" : "Not specified")],
      ["Capabilities", Array.isArray(projectSpec.capabilities) ? projectSpec.capabilities.join(", ") : ""],
      ["Verifier", Array.isArray(projectSpec.verifier) ? "Workestra-managed trusted verifier" : "Research required"],
    ];
    for (const [label, value] of details) {
      if (value) project.append(textElement("p", "preview-project-detail", `${label}: ${value}`));
    }
    if (research.length) {
      project.append(textElement("p", "preview-project-warning", `Research required: ${research.map((item) => item.topic).join(", ")}`));
    }
    preview.append(project);
  }
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
  rawDetails.append(textElement("summary", "", "Advanced: raw compiled plan"));
  rawDetails.append(textElement("pre", "output", JSON.stringify(raw, null, 2)));
  preview.append(rawDetails);
}

function planStatusLabel(plan) {
  if (plan.compiled) {
    const attempt = plan.last_compile_attempt;
    if (attempt?.status && attempt.status !== "compiled") {
      const reason = attempt.error || (attempt.unresolved_issues || []).join("; ") || "No reason provided.";
      return [`Compiled revision retained; latest compile failed: ${reason}`, "compiled"];
    }
    return ["Compiled plan ready", "compiled"];
  }
  if (plan.status === "needs_recompile") return ["Recompile required", "error"];
  if (plan.status === "rejected") return [`Rejected: ${(plan.unresolved_issues || []).join("; ") || "No rejection reason provided."}`, "error"];
  if (plan.status === "failed") return [plan.error || "Compilation failed", "error"];
  return ["Saved draft", "draft"];
}

function renderRunList(items, targetId = "run-list") {
  const list = $(targetId);
  if (!list) return;
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
    button.className = targetId === "history-list" ? "history-item" : "run-list-item";
    button.dataset.runId = runId;
    button.dataset.status = status;
    button.setAttribute("aria-current", runId === state.runId ? "true" : "false");
    const statusBadge = textElement("span", "badge", status.replaceAll("_", " "));
    statusBadge.dataset.status = status;
    const meta = textElement("span", targetId === "history-list" ? "history-item-meta" : "run-list-meta");
    meta.append(
      textElement("span", "", `${taskProgress(run)} tasks`),
      textElement("span", "", formatDuration(run)),
      statusBadge,
    );
    button.append(
      textElement("span", targetId === "history-list" ? "history-item-title" : "run-list-title", run.request || runId),
      textElement("span", targetId === "history-list" ? "history-item-id" : "run-list-id", runId),
      meta,
    );
    if (failureClass(run)) button.append(textElement("span", "run-failure-class", failureClass(run)));
    button.onclick = () => selectRun(runId);
    list.append(button);
  }
}

function syncRunListSelection() {
  for (const button of document.querySelectorAll("#run-list .run-list-item, #history-list .history-item")) {
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

function syncPlanActions() {
  const current = Boolean(state.planId && state.compiledPlanId === state.planId && state.compiledPlanRevision?.id);
  const greenfield = state.compiledProjectSpec?.intent === "new";
  const project = selectedProjectRecord();
  const needsCreation = greenfield && !state.compiledPlanProjectId;
  const correctGreenfieldProject = greenfield && project?.id === state.compiledPlanProjectId;
  const correctBoundProject = project?.id === state.compiledPlanProjectId;
  const startableProject = state.compiledPlanProjectId ? correctBoundProject : Boolean(project);
  $("start-run").textContent = needsCreation ? "Create & Start" : "Start";
  $("create-project").hidden = !needsCreation;
  $("create-project").disabled = !current || !needsCreation || !state.projectCreationEligible;
  $("start-run").disabled = !current || (needsCreation ? !state.projectCreationEligible : !startableProject);
  let startHint = needsCreation
    ? "This compiled greenfield plan will create its trusted workspace and start the run."
    : "Plan is ready to start.";
  if (!current) {
    startHint = "Compile or recompile the selected plan to enable its primary action.";
  } else if (needsCreation && !state.projectCreationEligible) {
    startHint = "Creation is blocked; see the exact eligibility reason above.";
  } else if (greenfield && !needsCreation && !correctGreenfieldProject) {
    startHint = state.projects.some((item) => item.id === state.compiledPlanProjectId)
      ? "Select the project bound to this compiled plan before starting."
      : "The project bound to this plan is no longer registered; restore it before starting.";
  } else if (state.compiledPlanProjectId && !correctBoundProject) {
    startHint = state.projects.some((item) => item.id === state.compiledPlanProjectId)
      ? "Select the project bound to this compiled plan before starting."
      : "The project bound to this plan is no longer registered; restore it before starting.";
  } else if (!startableProject) {
    startHint = "Select a project before starting this plan.";
  }
  $("start-plan-hint").textContent = startHint;
}

async function refreshProjectEligibility(plan) {
  state.compiledProjectSpec = plan?.project_spec || null;
  state.compiledPlanProjectId = plan?.project_id || null;
  state.projectCreationEligible = false;
  if (state.compiledPlanProjectId) {
    const project = state.projects.find((item) => item.id === state.compiledPlanProjectId);
    if (project) {
      $("project-select").value = project.id;
      state.projectId = project.id;
      $("project-detail").textContent = project.workspace_root || project.path;
    } else {
      $("project-select").value = "";
      state.projectId = null;
    }
  }
  if (state.compiledProjectSpec?.intent !== "new") {
    $("project-eligibility").textContent = state.compiledPlanProjectId
      ? `Bound to ${state.compiledPlanProjectId}; Start uses this project.`
      : "This plan needs an existing project selection before it can start.";
    syncPlanActions();
    return;
  }
  if (plan?.project_id) {
    const project = state.projects.find((item) => item.id === plan.project_id);
    $("project-eligibility").textContent = project
      ? `Bound to ${project.name}; Start uses this project.`
      : `Blocked: bound project ${plan.project_id} is not registered.`;
    syncPlanActions();
    return;
  }
  if (!plan?.compiled) {
    const reasons = (plan?.unresolved_issues || []).join("; ");
    $("project-eligibility").textContent = reasons ? `Blocked: ${reasons}` : "Compile this plan before creating a project.";
    syncPlanActions();
    return;
  }
  const identity = compiledPlanIdentity(plan);
  if (!identity.id) {
    $("project-eligibility").textContent = "Blocked: compiled revision is unavailable.";
    syncPlanActions();
    return;
  }
  try {
    const result = await request(`/plans/${encodeURIComponent(state.planId)}/eligibility?compiled_revision=${encodeURIComponent(identity.id)}`);
    if (state.planId !== plan.id && plan.id) return;
    state.projectCreationEligible = result.eligible === true;
    const name = result.project_spec?.name || state.compiledProjectSpec.name || "project";
    const path = result.project_spec?.workspace_root || state.compiledProjectSpec.workspace_root || "workspace unavailable";
    $("project-eligibility").textContent = state.projectCreationEligible
      ? `Ready to create ${name} at ${path}.`
      : `Blocked: ${(result.reasons || []).join("; ") || "Control did not approve project creation."}`;
  } catch (error) {
    $("project-eligibility").textContent = `Eligibility unavailable: ${error.message}`;
    state.projectCreationEligible = false;
  }
  syncPlanActions();
}

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
  const failed = status === "failed";
  const waitingForApproval = status === "waiting_for_approval";
  $("resume-run").textContent = waitingForApproval ? "Approve & resume" : "Resume";
  $("resume-run").setAttribute("aria-label", waitingForApproval ? "Approve current task and resume run" : "Resume run");
  $("resume-run").disabled = !hasRun || !waitingForApproval;
  // The synchronous engine has no safe pause/cancel primitive yet.
  $("pause-run").disabled = true;
  $("cancel-run").disabled = true;
  $("archive-run").disabled = !hasRun || !terminal || !failed;
  $("archive-run").title = failed ? "Remove this failed run from normal history; diagnostics stay archived." : "Only failed runs can be removed from normal history.";
  // Keep the destructive filesystem cleanup out of the normal Control path.
  $("cleanup-run").disabled = true;
}

function storedPlans() {
  const plans = readStorage(PLAN_STORAGE_KEY, []);
  return Array.isArray(plans) ? plans : [];
}

function saveSelectedPlan(projectId, planId) {
  const selected = readStorage(SELECTED_PLAN_STORAGE_KEY, {});
  if (selected && typeof selected === "object") {
    selected[projectId] = planId;
    writeStorage(SELECTED_PLAN_STORAGE_KEY, selected);
  }
}

function rememberPlan(record) {
  const plans = [record, ...storedPlans().filter((plan) => plan.id !== record.id)].slice(0, 30);
  writeStorage(PLAN_STORAGE_KEY, plans);
  saveSelectedPlan(record.project_id || "unbound", record.id);
}

function renderPlanHistory() {
  const select = $("plan-history");
  select.replaceChildren();
  if (!state.planGroups.length) {
    select.add(new Option("No saved source plans", ""));
    $("reuse-plan").disabled = true;
    $("plan-history-details").textContent = "No source plan selected.";
    return;
  }
  for (const group of state.planGroups) {
    const good = group.latest_good ? ` · reusable R${group.latest_good.revision}` : " · recompile required";
    const failed = group.attempts.filter((attempt) => attempt.status !== "compiled").length;
    select.add(new Option(`${group.title}${good}${failed ? ` · ${failed} failed` : ""}`, group.source_digest));
  }
  const preferred = localStorage.getItem(SELECTED_SOURCE_STORAGE_KEY);
  select.value = state.planGroups.some((group) => group.source_digest === preferred)
    ? preferred
    : state.planGroups[0].source_digest;
  $("reuse-plan").disabled = false;
  renderPlanHistoryDetails(state.planGroups.find((group) => group.source_digest === select.value));
}

function renderPlanHistoryDetails(group) {
  const details = $("plan-history-details");
  details.replaceChildren();
  if (!group) { details.textContent = "No source plan selected."; return; }
  const latest = group.latest_good ? `Latest reusable revision: R${group.latest_good.revision} (${group.latest_good.plan_id}).` : "No successful reusable revision; compile required.";
  details.append(textElement("p", "", `Source ${group.source_digest.slice(0, 12)} · ${group.plan_ids.length} saved record(s). ${latest}`));
  const attempts = textElement("p", "", `Compile attempts: ${group.attempts.length}; failed: ${group.attempts.filter((item) => item.status !== "compiled").length}.`);
  details.append(attempts);
  const latestAttempt = group.latest_attempt;
  if (latestAttempt?.error) details.append(textElement("p", "", `Latest attempt: ${latestAttempt.status} — ${latestAttempt.error}`));
  const history = document.createElement("details");
  history.append(textElement("summary", "", "Inspect compile attempts and revisions"));
  for (const attempt of group.attempts) {
    const message = `${attempt.status} · ${attempt.plan_id} · ${attempt.finished_at || "time unavailable"}${attempt.error ? ` — ${attempt.error}` : ""}`;
    history.append(textElement("p", "", message));
  }
  for (const revision of group.revisions) {
    history.append(textElement("p", "", `R${revision.revision} · ${revision.plan_id} · ${revision.reusable ? "reusable" : revision.reason || "not reusable"}`));
  }
  details.append(history);
}

async function refreshPlans() {
  const response = await request("/plan-history");
  const groups = Array.isArray(response.data || response) ? (response.data || response) : [];
  state.planGroups = groups;
  const planResponse = await request("/plans");
  const plans = Array.isArray(planResponse.data || planResponse) ? (planResponse.data || planResponse) : [];
  writeStorage(PLAN_STORAGE_KEY, plans);
  renderPlanHistory();
  if (state.planGroups.length) await reusePlan($("plan-history").value);
  else clearSelectedPlan();
}

function clearSelectedPlan() {
  state.planId = null;
  state.compiledPlanId = null;
  state.compiledPlanRevision = null;
  state.compiledPlanProjectId = null;
  state.compiledProjectSpec = null;
  state.projectCreationEligible = false;
  $("recompile-plan").hidden = true;
  $("recompile-plan").disabled = true;
  $("start-run").disabled = true;
  $("create-project").hidden = true;
  $("create-project").disabled = true;
  $("plan-revision").textContent = "Revision unavailable";
  setStatus("plan-status", "No plan selected", "idle");
  $("project-eligibility").textContent = "Select or import a plan.";
  syncPlanActions();
}

async function refreshProjects() {
  const projects = await request("/projects");
  const items = projects.data || projects;
  state.projects = Array.isArray(items) ? items : [];
  const select = $("project-select");
  const options = [new Option("New project from compiled plan", "")];
  options.push(...state.projects.map((project) => {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = `${project.name} — ${project.workspace_root || project.path}`;
    return option;
  }));
  if (!options.length) {
    const option = new Option("No projects available", "");
    option.disabled = true;
    options.push(option);
  } else if (!state.projects.length) {
    const option = new Option("No existing projects", "");
    option.disabled = true;
    options.push(option);
  }
  select.replaceChildren(...options);
  if (state.projectId && state.projects.some((project) => project.id === state.projectId)) select.value = state.projectId;
  state.projectId = select.value || null;
  syncPlanActions();
  const project = state.projects.find((item) => item.id === state.projectId);
  $("project-detail").textContent = project
    ? (project.workspace_root || project.path || "Path unavailable")
    : "New projects use the compiled ProjectSpec and trusted bootstrap.";
  syncProjectActions();
  await refreshPlans();
}

function clearRunDetail() {
  if (state.eventSource) state.eventSource.close();
  stopRunTimer();
  state.eventSource = null;
  state.runId = null;
  state.currentTaskId = null;
  state.lastEventId = 0;
  state.activeRun = null;
  syncRunListSelection();
  $("run-detail").hidden = true;
  $("run-heading").textContent = "";
  setStatus("run-status", "", "unknown");
  $("active-run-duration").textContent = "—";
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
  const refreshGeneration = ++state.runRefreshGeneration;
  let runs;
  try {
    runs = await request(`/runs${query}`);
  } catch (error) {
    if (token === state.selectedRunToken) showError(error);
    return;
  }
  if (token !== state.selectedRunToken || refreshGeneration !== state.runRefreshGeneration) return;
  const items = Array.isArray(runs.data || runs) ? (runs.data || runs) : [];
  state.runs = items;
  renderRunList(items);
  renderRunList(items, "history-list");
  $("history-count").textContent = `${items.length} run${items.length === 1 ? "" : "s"}`;
  const selected = items.find((run) => (run.run_id || run.id) === state.runId);
  renderActiveRun(selected || items.find((run) => ["running", "waiting_for_approval", "pending"].includes(run.status)) || null);
  if (selected && token === state.selectedRunToken) await refreshRunDetail(state.runId, token, refreshGeneration);
}

async function refreshRunDetail(runId, token = state.selectedRunToken, refreshGeneration = state.runRefreshGeneration) {
  const projectId = selectedProject();
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const run = await request(`/runs/${encodeURIComponent(runId)}${query}`);
  if (!isCurrentRun(runId, token) || refreshGeneration !== state.runRefreshGeneration) return;
  $("run-detail").hidden = false;
  $("run-heading").textContent = `Run ${run.run_id || run.id}`;
  renderActiveRun(run);
  setStatus("run-status", run.status || "unknown", run.status || "unknown");
  renderTaskList(Array.isArray(run.tasks) ? run.tasks : []);
  syncRunActions();
}

async function selectRun(runId) {
  const token = ++state.selectedRunToken;
  clearRunDetail();
  state.runId = runId;
  switchWorkbench("run");
  syncRunListSelection();
  try {
    const projectId = selectedProject();
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
    const run = await request(`/runs/${encodeURIComponent(runId)}${query}`);
    if (!isCurrentRun(runId, token)) return;
    $("run-detail").hidden = false;
    $("run-heading").textContent = `Run ${run.run_id || run.id}`;
    state.currentTaskId = run.current_task || null;
    renderActiveRun(run);
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
  $("project-edit-form").hidden = false;
  $("project-edit-name").focus();
}

function projectEditPayload(project) {
  const current = {
    name: $("project-edit-name").value,
    path: $("project-edit-path").value,
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
  if (!runId) return;
  if (action === "archive" && $("run-status").textContent !== "failed") return;
  const message = action === "archive"
    ? `Remove failed run ${runId} from normal history? Its diagnostic archive will be kept in .archive.`
    : `${label} run ${runId}?`;
  if (!window.confirm(message)) return;
  try {
    await request(`/runs/${encodeURIComponent(runId)}/${action}`, {
      method: "POST",
      body: JSON.stringify({ project_id: projectId }),
    });
    if (state.runId === runId) invalidateRunSelection();
    renderActiveRun(null);
    await refreshRuns();
  } catch (error) {
    showError(error);
  }
}

async function reusePlan(sourceDigest = $("plan-history").value) {
  const group = state.planGroups.find((item) => item.source_digest === sourceDigest);
  if (!group) return;
  const planId = group.latest_good?.plan_id || group.latest_attempt?.plan_id || group.plan_ids.at(-1);
  const record = storedPlans().find((plan) => plan.id === planId);
  if (!record) return;
  const loadGeneration = ++state.planLoadGeneration;
  state.planId = record.id;
  localStorage.setItem(SELECTED_SOURCE_STORAGE_KEY, sourceDigest);
  renderPlanHistoryDetails(group);
  syncPlanActions();
  saveSelectedPlan(record.project_id || "unbound", record.id);
  setStatus("plan-status", "Loading saved plan", "loading");
  try {
    const plan = await request(`/plans/${encodeURIComponent(record.id)}`);
    if (loadGeneration !== state.planLoadGeneration || state.planId !== record.id) return;
    $("plan-markdown").value = plan.markdown || record.markdown || "";
    renderPlanPreview(plan);
    const identity = compiledPlanIdentity(plan);
    state.compiledPlanId = plan.compiled ? record.id : null;
    state.compiledPlanRevision = plan.compiled ? identity : null;
    state.compiledPlanProjectId = plan.project_id || null;
    state.compiledProjectSpec = plan.project_spec || null;
    if (state.compiledPlanProjectId && state.projects.some((project) => project.id === state.compiledPlanProjectId)) {
      $("project-select").value = state.compiledPlanProjectId;
      state.projectId = state.compiledPlanProjectId;
    } else if (!state.compiledPlanProjectId) {
      $("project-select").value = "";
      state.projectId = null;
    }
    $("recompile-plan").hidden = !state.planId;
    $("recompile-plan").disabled = !state.planId;
    const [label, status] = planStatusLabel(plan);
    setStatus("plan-status", label, status);
    await refreshProjectEligibility(plan);
  } catch (error) {
    if (loadGeneration === state.planLoadGeneration && state.planId === record.id) {
      syncPlanActions();
      setStatus("plan-status", `Unable to load plan: ${error.message}`, "error");
      showError(error);
    }
  }
}

async function compilePlan(planId) {
  const compileGeneration = ++state.compileGeneration;
  const hadCompiledRevision = state.compiledPlanId === planId && Boolean(state.compiledPlanRevision?.id);
  setStatus("plan-status", hadCompiledRevision ? "Recompiling; last good revision remains available" : "Compiling plan…", "loading");
  try {
    await request(`/plans/${encodeURIComponent(planId)}/compile`, {
      method: "POST",
      body: JSON.stringify({ force: true }),
    });
    if (compileGeneration !== state.compileGeneration || state.planId !== planId) return;
    const saved = await request(`/plans/${encodeURIComponent(planId)}`);
    if (compileGeneration !== state.compileGeneration || state.planId !== planId) return;
    rememberPlan(saved);
    renderPlanPreview(saved);
    const savedIdentity = compiledPlanIdentity(saved);
    state.compiledPlanId = saved.compiled ? planId : null;
    state.compiledPlanRevision = saved.compiled ? savedIdentity : null;
    state.compiledPlanProjectId = saved.project_id || null;
    state.compiledProjectSpec = saved.project_spec || null;
    const [label, status] = planStatusLabel(saved);
    setStatus("plan-status", label, status);
    await refreshProjectEligibility({ ...saved, project_spec: state.compiledProjectSpec });
    await refreshPlans();
  } catch (error) {
    if (compileGeneration === state.compileGeneration && state.planId === planId) {
      syncPlanActions();
      setStatus("plan-status", `${hadCompiledRevision ? "Last good revision retained; " : ""}compile attempt failed: ${error.message}`, hadCompiledRevision ? "compiled" : "error");
    }
    throw error;
  }
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

$("project-select").onchange = () => {
  invalidateRunSelection();
  state.projectId = $("project-select").value || null;
  syncProjectActions();
  syncPlanActions();
  refreshRuns().catch(showError);
};
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
async function createProjectForPlan(planId, revision) {
  const projectSpec = state.compiledProjectSpec;
  const project = await request(`/plans/${encodeURIComponent(planId)}/project`, {
    method: "POST",
    body: JSON.stringify({ compiled_revision: Number(revision.id) }),
  });
  await refreshProjects();
  state.planId = planId;
  state.compiledPlanId = planId;
  state.compiledPlanRevision = revision;
  state.compiledPlanProjectId = project.id;
  state.compiledProjectSpec = projectSpec;
  $("project-select").value = project.id;
  state.projectId = project.id;
  $("project-detail").textContent = project.workspace_root || project.path;
  $("project-eligibility").textContent = `Project ${project.name} is bound to this compiled plan.`;
  syncProjectActions();
  syncPlanActions();
  return project;
}

$("create-project").onclick = async () => {
  const planId = state.planId;
  const revision = state.compiledPlanRevision;
  if (!planId || !revision?.id || !state.projectCreationEligible) return;
  $("create-project").disabled = true;
  $("project-eligibility").textContent = "Creating project with trusted bootstrap…";
  try {
    const project = await createProjectForPlan(planId, revision);
    $("project-eligibility").textContent = `Created ${project.name}.`;
    setStatus("plan-status", "Project created; ready to start", "compiled");
    await refreshRuns();
  } catch (error) {
    $("project-eligibility").textContent = `Blocked: ${error.message}`;
    showError(error);
    syncPlanActions();
  }
};
$("plan-history").onchange = () => reusePlan().catch(showError);
$("reuse-plan").onclick = () => reusePlan().catch(showError);
$("recompile-plan").onclick = () => {
  if (state.planId) compilePlan(state.planId).catch(showError);
};
$("project-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await request("/projects", { method: "POST", body: JSON.stringify({ name: $("project-name").value, path: $("project-path").value }) });
    event.target.reset(); await refreshProjects();
  } catch (error) { showError(error); }
};
$("plan-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const markdown = $("plan-markdown").value;
    const projectId = selectedProject();
    const imported = await request("/plans/import", {
      method: "POST",
      body: JSON.stringify(projectId ? { project_id: projectId, markdown } : { markdown }),
    });
    state.planId = imported.id || imported.plan_id;
    if (imported.source_digest) localStorage.setItem(SELECTED_SOURCE_STORAGE_KEY, imported.source_digest);
    rememberPlan({ ...imported, id: state.planId, project_id: projectId, title: markdown.split("\n").find((line) => line.trim()) || "Untitled plan", markdown, created_at: new Date().toISOString() });
    await compilePlan(state.planId);
  } catch (error) { showError(error); }
};
$("start-run").onclick = async () => {
  const planId = state.planId;
  const revision = state.compiledPlanRevision;
  if (!planId || state.compiledPlanId !== planId || !revision?.id) return;
  const needsCreation = state.compiledProjectSpec?.intent === "new" && !state.compiledPlanProjectId;
  if (needsCreation && !state.projectCreationEligible) return;
  const label = $("start-run").textContent;
  let projectCreated = false;
  $("start-run").disabled = true;
  $("start-run").textContent = needsCreation ? "Creating & starting…" : "Starting…";
  setStatus("plan-status", needsCreation ? "Creating trusted workspace and starting run…" : "Starting run…", "loading");
  try {
    invalidateRunSelection();
    let projectId = state.compiledPlanProjectId || selectedProject();
    if (needsCreation) {
      projectId = (await createProjectForPlan(planId, revision)).id;
      projectCreated = true;
    }
    const body = {
      plan_id: planId,
      project_id: projectId,
      compiled_revision: Number(revision.id),
    };
    const run = await request("/runs", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const runId = run.run_id || run.id;
    await refreshRuns();
    if (runId) { state.runId = runId; await selectRun(runId); }
    else setStatus("plan-status", "Run accepted; refresh runs to inspect it", "compiled");
  }
  catch (error) {
    setStatus("plan-status", projectCreated ? "Project created; start failed" : needsCreation ? "Unable to create project" : "Unable to start run", "error");
    showError(error);
  }
  finally {
    if (state.planId === planId && state.compiledPlanId === planId && state.compiledPlanRevision?.id === revision.id) {
      syncPlanActions();
      if ($("start-run").disabled) $("start-run").textContent = label;
    }
  }
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
for (const tab of document.querySelectorAll("[data-workbench-tab]")) {
  tab.onclick = () => switchWorkbench(tab.dataset.workbenchTab);
}
$("active-run-open").onclick = () => {
  const runId = $("active-run-open").dataset.runId;
  if (runId) selectRun(runId);
};

async function refreshHealth() {
  try {
    const response = await request("/health");
    $("build-version").textContent = response?.version ? `Build ${response.version}` : "Build unknown";
    const healthy = response?.status === "ok";
    setStatus("health", healthy ? "Control plane online" : "Control plane degraded", healthy ? "ok" : "error");
  } catch (error) {
    $("build-version").textContent = "Build unavailable";
    setStatus("health", "Control plane offline", "error");
    showError(error);
  }
}

switchWorkbench("plan");
renderActiveRun(null);
Promise.all([refreshHealth(), refreshProjects()]).then(() => refreshRuns()).catch(showError);
