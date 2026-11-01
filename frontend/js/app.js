/**
 * CodeTrace notebook upload and API-health indicator.
 */

const API_BASE_URL = "http://127.0.0.1:8000";
const HEALTH_CHECK_INTERVAL_MS = 15_000;
const GENERIC_UPLOAD_ERROR = "Something went wrong. Please try again later.";
const healthIndicator = document.getElementById("api-health-indicator");
const uploadForm = document.getElementById("upload-form");
const uploadStage = document.getElementById("upload-stage");
const notebookFile = document.getElementById("notebook-file");
const uploadBtn = document.getElementById("upload-btn");
const uploadMessage = document.getElementById("upload-message");
const notebookSummary = document.getElementById("notebook-summary");
const summaryBody = document.getElementById("notebook-summary-body");
const inspectView = document.getElementById("inspect-view");
const aboutView = document.getElementById("about-view");
const workspace = document.getElementById("investigation-workspace");
const cellSelector = document.getElementById("cell-selector");
const cellMeta = document.getElementById("cell-meta");
const cellSource = document.getElementById("cell-source");
const datasetForm = document.getElementById("dataset-upload-form");
const datasetFile = document.getElementById("dataset-file");
const datasetUploadBtn = document.getElementById("dataset-upload-btn");
const datasetUploadMessage = document.getElementById("dataset-upload-message");
const datasetResults = document.getElementById("dataset-results");
const datasetColumns = document.getElementById("dataset-columns");
const executionDatasetForm = document.getElementById("execution-dataset-form");
const executionDatasetFile = document.getElementById("execution-dataset-file");
const executionDatasetMessage = document.getElementById("execution-dataset-message");
const executionDatasetList = document.getElementById("execution-datasets");
const executionDatasetSelect = document.getElementById("execution-dataset-select");
const executionNotebookSelect = document.getElementById("execution-notebook");
const executionForm = document.getElementById("execution-form");
const startExecutionButton = document.getElementById("start-execution-btn");
const cancelExecutionButton = document.getElementById("cancel-execution-btn");
const executionStatusMessage = document.getElementById("execution-status");
const executionResult = document.getElementById("execution-result");
const executionOutputs = document.getElementById("execution-outputs");
const loadVerificationExecutionsButton = document.getElementById("load-verification-executions");
const verificationOriginalExecution = document.getElementById("verification-original-execution");
const verificationCorrectedExecution = document.getElementById("verification-corrected-execution");
const startVerificationButton = document.getElementById("start-verification");
const verificationStatusMessage = document.getElementById("verification-status-message");
const verificationResults = document.getElementById("verification-results");
const generateReportButton = document.getElementById("generate-report");
const loadReportsButton = document.getElementById("load-reports");
const reportStatusMessage = document.getElementById("report-status");
const reportList = document.getElementById("report-list");
const reportArtifactList = document.getElementById("report-artifact-list");
const reportPreviewContainer = document.getElementById("report-preview-container");
const reportPreview = document.getElementById("report-preview");
const overlapForm = document.getElementById("overlap-form");
const overlapTrainFile = document.getElementById("overlap-train-file");
const overlapTestFile = document.getElementById("overlap-test-file");
const overlapSubmit = document.getElementById("overlap-submit");
const overlapMessage = document.getElementById("overlap-message");
const overlapResults = document.getElementById("overlap-results");
let currentNotebook = null;
let currentNotebookFile = null;
let currentNotebookId = null;
let currentNotebookToken = null;
let correctedNotebookId = null;
let currentExecutionId = null;
let currentVerificationId = null;
let executionPollTimer = null;
let currentPipelineTrace = null;
let repairDecisions = new Map();
let pipelineGraphLayout = null;
let graphViewBox = null;
let graphInitialViewBox = null;
let graphSelectedItem = null;
let graphHighlightFindingPaths = false;
let graphSelectedFindingId = null;
let healthCheckInProgress = false;
let uploadInProgress = false;
let datasetUploadInProgress = false;
let overlapCheckInProgress = false;

cellSelector.addEventListener("change", () => selectCell(Number(cellSelector.value)));

document.getElementById("graph-type-filters").addEventListener("change", renderPipelineSvg);
document.getElementById("graph-finding-filter").addEventListener("change", renderPipelineSvg);
document.getElementById("finding-severity-filter").addEventListener("change", () => {
  renderFindings(getCurrentFindings());
});
document.getElementById("finding-category-filter").addEventListener("change", () => {
  renderFindings(getCurrentFindings());
});
document.getElementById("graph-zoom-in").addEventListener("click", () => zoomPipelineGraph(0.8));
document.getElementById("graph-zoom-out").addEventListener("click", () => zoomPipelineGraph(1.25));
document.getElementById("graph-fit").addEventListener("click", fitPipelineGraph);
document.getElementById("graph-reset").addEventListener("click", resetPipelineGraph);
document.getElementById("graph-highlight-findings").addEventListener("click", (event) => {
  graphHighlightFindingPaths = !graphHighlightFindingPaths;
  graphSelectedFindingId = null;
  event.currentTarget.setAttribute("aria-pressed", String(graphHighlightFindingPaths));
  renderPipelineSvg();
});
document.getElementById("graph-edges").addEventListener("click", (event) => {
  const button = event.target.closest("[data-edge-id]");
  if (button) {
    selectPipelineEdge(button.dataset.edgeId);
  }
});
document.getElementById("findings-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-finding-action]");
  if (!button) {
    return;
  }
  const finding = getCurrentFindings().find((item) => item.id === button.dataset.findingId);
  if (!finding) {
    return;
  }
  if (button.dataset.findingAction === "source") {
    const cellIndex = finding.cell_indices[0];
    if (Number.isInteger(cellIndex)) {
      selectCell(cellIndex);
      window.location.hash = "#cells";
    }
  } else if (button.dataset.findingAction === "pipeline") {
    openFindingPipelineNode(finding, button.dataset.nodeId);
  } else if (button.dataset.findingAction === "path") {
    highlightGraphForFinding(finding);
  }
});
document.getElementById("repairs-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-repair-action]");
  if (!button) {
    return;
  }
  const repairId = button.dataset.repairId;
  repairDecisions.set(repairId, button.dataset.repairAction);
  renderRepairCenter(getCurrentRepairProposals());
});
document.getElementById("graph-inspect-source").addEventListener("click", () => {
  if (graphSelectedItem && graphSelectedItem.type === "node") {
    selectCell(graphSelectedItem.item.cell_index);
    window.location.hash = "#cells";
  }
});

const graphViewport = document.getElementById("graph-viewport");
graphViewport.addEventListener("pointerdown", (event) => {
  if (event.target.closest(".pipeline-node, .pipeline-edge")) {
    return;
  }
  graphViewport.setPointerCapture(event.pointerId);
  graphViewport.classList.add("is-panning");
  graphViewport.dataset.panStartX = String(event.clientX);
  graphViewport.dataset.panStartY = String(event.clientY);
  graphViewport.dataset.panViewBox = graphViewBox ? JSON.stringify(graphViewBox) : "";
});
graphViewport.addEventListener("pointermove", (event) => {
  if (!graphViewport.hasPointerCapture(event.pointerId) || !graphViewBox) {
    return;
  }
  const initialView = JSON.parse(graphViewport.dataset.panViewBox || "null");
  if (!initialView) {
    return;
  }
  const rect = document.getElementById("pipeline-graph").getBoundingClientRect();
  const deltaX = event.clientX - Number(graphViewport.dataset.panStartX);
  const deltaY = event.clientY - Number(graphViewport.dataset.panStartY);
  graphViewBox = {
    ...initialView,
    x: initialView.x - deltaX * initialView.width / rect.width,
    y: initialView.y - deltaY * initialView.height / rect.height
  };
  updatePipelineViewBox();
});
graphViewport.addEventListener("pointerup", (event) => {
  if (graphViewport.hasPointerCapture(event.pointerId)) {
    graphViewport.releasePointerCapture(event.pointerId);
  }
  graphViewport.classList.remove("is-panning");
});
graphViewport.addEventListener("pointercancel", () => graphViewport.classList.remove("is-panning"));
graphViewport.addEventListener("wheel", (event) => {
  if (!currentPipelineTrace || !graphViewBox) {
    return;
  }
  event.preventDefault();
  zoomPipelineGraph(event.deltaY < 0 ? 0.88 : 1.14);
}, { passive: false });

function setHealth(state, label) {
  healthIndicator.dataset.health = state;
  healthIndicator.setAttribute("aria-label", label);
  healthIndicator.title = label;
}

async function checkApiHealth() {
  if (healthCheckInProgress) {
    return;
  }

  healthCheckInProgress = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`, {
      cache: "no-store"
    });
    if (!response.ok) {
      setHealth("unhealthy", "API is unavailable");
      return;
    }

    const data = await response.json();
    if (data && data.status === "healthy" && data.service === "CodeTrace API") {
      setHealth("healthy", "API is healthy");
    } else {
      setHealth("unhealthy", "API returned an invalid health response");
    }
  } catch {
    setHealth("unhealthy", "API is unavailable");
  } finally {
    healthCheckInProgress = false;
  }
}

setHealth("checking", "Checking API health");
checkApiHealth();
window.setInterval(checkApiHealth, HEALTH_CHECK_INTERVAL_MS);

function showRoute() {
  const aboutIsVisible = window.location.hash === "#about";
  let workspaceRoute = window.location.hash.slice(1);
  if (workspaceRoute === "inspect") {
    workspaceRoute = currentNotebook ? "summary" : "upload";
  }
  const validWorkspaceRoutes = ["summary", "overview", "pipeline", "audit", "repairs", "execution", "verification", "cells", "evidence"];
  if (!validWorkspaceRoutes.includes(workspaceRoute)) {
    workspaceRoute = currentNotebook ? "summary" : "upload";
  }
  const hasNotebook = Boolean(currentNotebook);
  const showWorkspace = !aboutIsVisible && hasNotebook;
  const showUpload = !aboutIsVisible && !hasNotebook;

  inspectView.classList.toggle("hidden", aboutIsVisible);
  aboutView.classList.toggle("hidden", !aboutIsVisible);
  uploadStage.classList.toggle("hidden", !showUpload);
  workspace.classList.toggle("hidden", !showWorkspace);
  if (showWorkspace) {
    document.querySelectorAll("[data-workspace-page]").forEach((page) => {
      page.classList.toggle("hidden", page.dataset.workspacePage !== workspaceRoute);
    });
    document.querySelectorAll("[data-workspace-route]").forEach((link) => {
      if (link.dataset.workspaceRoute === workspaceRoute) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
    if (workspaceRoute === "pipeline" && pipelineGraphLayout) {
      window.requestAnimationFrame(fitPipelineGraph);
    }
  }
  document.querySelectorAll(".primary-nav a").forEach((link) => {
    if (link.dataset.route === (aboutIsVisible ? "about" : "inspect")) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
}

if (!window.location.hash) {
  window.history.replaceState(null, "", "#about");
}

window.addEventListener("hashchange", showRoute);
showRoute();

notebookFile.addEventListener("change", () => {
  if (notebookFile.files.length > 0) {
    clearUploadMessage();
  }
});

datasetFile.addEventListener("change", () => {
  if (datasetFile.files.length > 0) {
    clearDatasetMessage();
  }
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (uploadInProgress) {
    return;
  }

  const selectedFile = notebookFile.files[0];
  if (!selectedFile) {
    showUploadMessage("Choose a .ipynb file to upload.", "error");
    notebookFile.focus();
    return;
  }

  uploadInProgress = true;
  uploadBtn.disabled = true;
  uploadBtn.textContent = "Uploading…";
  showUploadMessage("Validating notebook…", "loading");
  notebookSummary.classList.add("hidden");
  summaryBody.replaceChildren();

  try {
    const formData = new FormData();
    formData.append("file", selectedFile);
    const response = await fetch(`${API_BASE_URL}/api/notebooks/upload`, {
      method: "POST",
      body: formData
    });

    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("The server returned a non-JSON response.");
    }

    if (!response.ok) {
      const message = response.status >= 500
        ? GENERIC_UPLOAD_ERROR
        : data && data.detail && typeof data.detail.message === "string"
          ? data.detail.message
          : "The upload could not be completed. Please check the file and try again.";
      showUploadMessage(message, "error");
      return;
    }

    if (
      !isNotebookSuccessResponse(data) ||
      typeof data.notebook_id !== "string" ||
      typeof data.access_token !== "string"
    ) {
      showUploadMessage("The server response did not contain a valid notebook summary or access token.", "error");
      return;
    }

    currentNotebook = data.notebook;
    currentNotebookFile = selectedFile;
    currentNotebookId = data.notebook_id;
    currentNotebookToken = data.access_token;
    correctedNotebookId = null;
    currentExecutionId = null;
    currentVerificationId = null;
    verificationOriginalExecution.replaceChildren(new Option("Select an execution", ""));
    verificationCorrectedExecution.replaceChildren(new Option("Select an execution", ""));
    verificationResults.replaceChildren();
    showVerificationStatus("", "hidden");
    reportList.replaceChildren();
    reportArtifactList.replaceChildren();
    reportPreview.srcdoc = "";
    reportPreviewContainer.classList.add("hidden");
    showReportStatus("", "hidden");
    executionDatasetSelect.replaceChildren();
    executionDatasetList.replaceChildren();
    executionNotebookSelect.replaceChildren(
      new Option("Original notebook", "original")
    );
    executionResult.classList.add("hidden");
    executionStatusMessage.textContent = "";
    resetRepairWorkflow();
    showNotebookSummary(data.notebook);
    if (!renderInvestigation(data.notebook)) {
      currentNotebook = null;
      currentNotebookFile = null;
      currentNotebookId = null;
      currentNotebookToken = null;
      repairDecisions = new Map();
      showUploadMessage("Notebook parsed, but the analysis response was incomplete.", "error");
      return;
    }
    uploadStage.classList.add("hidden");
    window.location.hash = "#summary";
  } catch {
    showUploadMessage(GENERIC_UPLOAD_ERROR, "error");
  } finally {
    uploadInProgress = false;
    uploadBtn.disabled = false;
    uploadBtn.textContent = "Upload Notebook";
  }
});

document.getElementById("choose-another-notebook").addEventListener("click", () => {
  if (executionPollTimer !== null) {
    window.clearTimeout(executionPollTimer);
    executionPollTimer = null;
  }
  currentNotebook = null;
  currentNotebookFile = null;
  currentNotebookId = null;
  currentNotebookToken = null;
  correctedNotebookId = null;
  currentExecutionId = null;
  currentVerificationId = null;
  resetRepairWorkflow();
  verificationOriginalExecution.replaceChildren(new Option("Select an execution", ""));
  verificationCorrectedExecution.replaceChildren(new Option("Select an execution", ""));
  verificationResults.replaceChildren();
  showVerificationStatus("", "hidden");
  reportList.replaceChildren();
  reportArtifactList.replaceChildren();
  reportPreview.srcdoc = "";
  reportPreviewContainer.classList.add("hidden");
  showReportStatus("", "hidden");
  executionDatasetList.replaceChildren();
  executionDatasetSelect.replaceChildren();
  executionDatasetForm.reset();
  showExecutionDatasetMessage("", "hidden");
  executionNotebookSelect.replaceChildren(
    new Option("Original notebook", "original")
  );
  executionResult.classList.add("hidden");
  executionStatusMessage.textContent = "";
  datasetForm.reset();
  resetDatasetAnalysis();
  uploadForm.reset();
  clearUploadMessage();
  notebookSummary.classList.add("hidden");
  workspace.classList.add("hidden");
  uploadStage.classList.remove("hidden");
  window.location.hash = "#inspect";
  showRoute();
  notebookFile.focus();
});

datasetForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (datasetUploadInProgress) {
    return;
  }

  const selectedFile = datasetFile.files[0];
  if (!selectedFile) {
    showDatasetMessage("Choose a .csv file to analyze.", "error");
    datasetFile.focus();
    return;
  }

  datasetUploadInProgress = true;
  datasetUploadBtn.disabled = true;
  datasetUploadBtn.textContent = "Analyzing…";
  datasetResults.classList.add("hidden");
  datasetColumns.replaceChildren();
  showDatasetMessage("Analyzing the uploaded CSV…", "loading");

  try {
    const formData = new FormData();
    formData.append("file", selectedFile);
    const response = await fetch(`${API_BASE_URL}/api/datasets/analyze`, {
      method: "POST",
      body: formData
    });

    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("The server returned a non-JSON response.");
    }

    if (!response.ok) {
      const message = response.status >= 500
        ? GENERIC_UPLOAD_ERROR
        : data && data.detail && typeof data.detail.message === "string"
          ? data.detail.message
          : "The dataset could not be analyzed. Please check the file and try again.";
      showDatasetMessage(message, "error");
      return;
    }

    if (!isDatasetSuccessResponse(data)) {
      showDatasetMessage("The server response did not contain a valid dataset profile.", "error");
      return;
    }

    renderDatasetAnalysis(data.dataset);
    showDatasetMessage("CSV analysis complete. Only aggregate profile data is displayed.", "success");
  } catch {
    showDatasetMessage(GENERIC_UPLOAD_ERROR, "error");
  } finally {
    datasetUploadInProgress = false;
    datasetUploadBtn.disabled = false;
    datasetUploadBtn.textContent = "Analyze CSV";
  }
});

executionDatasetForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentNotebookId || !currentNotebookToken) {
    showExecutionDatasetMessage("Upload a notebook before attaching a dataset.", "error");
    return;
  }
  const file = executionDatasetFile.files[0];
  if (!file) {
    showExecutionDatasetMessage("Choose a CSV dataset to attach.", "error");
    executionDatasetFile.focus();
    return;
  }
  const button = document.getElementById("execution-dataset-btn");
  button.disabled = true;
  button.textContent = "Adding…";
  showExecutionDatasetMessage("Validating and associating this CSV…", "loading");
  try {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(
      `${API_BASE_URL}/api/notebooks/${encodeURIComponent(currentNotebookId)}/datasets`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${currentNotebookToken}` },
        body: formData
      }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail?.message || "The dataset could not be attached.");
    }
    if (!data.dataset || typeof data.dataset.dataset_id !== "string") {
      throw new Error("The server did not return a valid dataset reference.");
    }
    const option = new Option(data.dataset.filename, data.dataset.dataset_id);
    executionDatasetSelect.add(option);
    const item = document.createElement("li");
    item.textContent = `${data.dataset.filename} · available only when selected for an experiment`;
    executionDatasetList.appendChild(item);
    executionDatasetFile.value = "";
    showExecutionDatasetMessage("Dataset securely associated with this notebook.", "success");
  } catch (error) {
    showExecutionDatasetMessage(
      error instanceof Error ? error.message : "The dataset could not be attached.",
      "error"
    );
  } finally {
    button.disabled = false;
    button.textContent = "Add dataset for execution";
  }
});

executionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentNotebookId || !currentNotebookToken) {
    showExecutionStatus("Upload a notebook before starting an experiment.", "error");
    return;
  }
  const notebookId = executionNotebookSelect.value === "corrected"
    ? correctedNotebookId
    : currentNotebookId;
  if (!notebookId) {
    showExecutionStatus("Generate an approved corrected notebook before selecting it.", "error");
    return;
  }

  startExecutionButton.disabled = true;
  startExecutionButton.textContent = "Starting…";
  executionResult.classList.add("hidden");
  showExecutionStatus("Requesting an isolated Docker execution…", "loading");
  const datasetIds = [...executionDatasetSelect.selectedOptions].map((option) => option.value);
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/notebooks/${encodeURIComponent(notebookId)}/executions`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${currentNotebookToken}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ dataset_ids: datasetIds })
      }
    );
    const data = await response.json();
    const execution = data?.execution || data?.detail?.execution || data;
    if (execution && typeof execution.execution_id === "string") {
      currentExecutionId = execution.execution_id;
      renderExecution(execution);
    }
    if (!response.ok) {
      const message = data?.detail?.message || "The execution could not be started.";
      if (execution && execution.status === "unavailable") {
        showExecutionStatus(message, "error");
        return;
      }
      throw new Error(message);
    }
    if (!execution || typeof execution.execution_id !== "string") {
      throw new Error("The server did not return a valid execution record.");
    }
    showExecutionStatus(`Execution ${execution.status}.`, "loading");
    scheduleExecutionPoll();
  } catch (error) {
    currentExecutionId = null;
    showExecutionStatus(
      error instanceof Error ? error.message : "The execution could not be started.",
      "error"
    );
    startExecutionButton.disabled = false;
    startExecutionButton.textContent = "Start execution";
  }
});

cancelExecutionButton.addEventListener("click", async () => {
  if (!currentExecutionId || !currentNotebookToken) {
    return;
  }
  cancelExecutionButton.disabled = true;
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/executions/${encodeURIComponent(currentExecutionId)}/cancel`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${currentNotebookToken}` }
      }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail?.message || "The execution could not be cancelled.");
    }
    renderExecution(data);
    showExecutionStatus(
      data.status === "cancelled"
        ? "Execution cancelled."
        : `Cancellation ended with execution status ${executionStatusLabel(data.status).toLowerCase()}.`,
      data.status === "cancelled" ? "success" : "error"
    );
    stopExecutionPolling();
  } catch (error) {
    showExecutionStatus(
      error instanceof Error ? error.message : "The execution could not be cancelled.",
      "error"
    );
  } finally {
    cancelExecutionButton.disabled = false;
  }
});

document.getElementById("download-executed-notebook").addEventListener("click", async () => {
  if (!currentExecutionId || !currentNotebookToken) {
    return;
  }
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/executions/${encodeURIComponent(currentExecutionId)}/notebook`,
      { headers: { Authorization: `Bearer ${currentNotebookToken}` } }
    );
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data?.detail?.message || "The executed notebook is not available.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${currentNotebook.filename.replace(/\.ipynb$/i, "")}-executed.ipynb`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    showExecutionStatus(
      error instanceof Error ? error.message : "The executed notebook is not available.",
      "error"
    );
  }
});

function showExecutionDatasetMessage(message, state) {
  executionDatasetMessage.textContent = message;
  executionDatasetMessage.className = `upload-message ${state}`;
}

function showExecutionStatus(message, state) {
  executionStatusMessage.textContent = message;
  executionStatusMessage.className = `graph-status ${state}`;
}

function stopExecutionPolling() {
  if (executionPollTimer !== null) {
    window.clearTimeout(executionPollTimer);
    executionPollTimer = null;
  }
  startExecutionButton.disabled = false;
  startExecutionButton.textContent = "Start execution";
  cancelExecutionButton.classList.add("hidden");
}

function scheduleExecutionPoll() {
  if (executionPollTimer !== null) {
    window.clearTimeout(executionPollTimer);
  }
  executionPollTimer = window.setTimeout(pollExecution, 1500);
}

async function pollExecution() {
  if (!currentExecutionId || !currentNotebookToken) {
    stopExecutionPolling();
    return;
  }
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/executions/${encodeURIComponent(currentExecutionId)}`,
      {
        headers: { Authorization: `Bearer ${currentNotebookToken}` },
        cache: "no-store"
      }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail?.message || "Execution status could not be loaded.");
    }
    renderExecution(data);
    if (["queued", "running"].includes(data.status)) {
      showExecutionStatus(`Execution ${data.status}.`, "loading");
      scheduleExecutionPoll();
    } else {
      const label = executionStatusLabel(data.status);
      showExecutionStatus(`Execution ${label.toLowerCase()}.`, data.status === "completed" ? "success" : "error");
      stopExecutionPolling();
    }
  } catch (error) {
    showExecutionStatus(
      error instanceof Error ? error.message : "Execution status could not be loaded.",
      "error"
    );
    stopExecutionPolling();
  }
}

function executionStatusLabel(status) {
  return ({
    queued: "Queued",
    running: "Running",
    completed: "Completed",
    failed: "Failed",
    timed_out: "Timed out",
    cancelled: "Cancelled",
    unavailable: "Unavailable"
  })[status] || "Unknown";
}

function renderExecution(execution) {
  executionResult.classList.remove("hidden");
  document.getElementById("execution-id").textContent = execution.execution_id;
  document.getElementById("execution-state").textContent = executionStatusLabel(execution.status);
  document.getElementById("execution-duration").textContent =
    typeof execution.duration_seconds === "number"
      ? `${execution.duration_seconds.toFixed(2)} seconds`
      : "Not complete";
  document.getElementById("execution-cells").textContent = String(execution.executed_cell_count ?? 0);
  document.getElementById("execution-successful").textContent =
    String(execution.successful_cell_count ?? 0);
  document.getElementById("execution-failed-cell").textContent =
    execution.failed_cell_number === null || execution.failed_cell_number === undefined
      ? "None"
      : `Cell ${execution.failed_cell_number}`;
  const errorElement = document.getElementById("execution-error");
  if (execution.error_details) {
    errorElement.textContent = [
      execution.error_details.ename,
      execution.error_details.evalue,
      execution.error_details.traceback,
      execution.error_details.message
    ].filter(Boolean).join("\n");
    errorElement.classList.remove("hidden");
  } else {
    errorElement.textContent = "";
    errorElement.classList.add("hidden");
  }
  const downloadButton = document.getElementById("download-executed-notebook");
  downloadButton.classList.toggle(
    "hidden",
    !execution.artifact_available
  );
  cancelExecutionButton.classList.toggle(
    "hidden",
    !["queued", "running"].includes(execution.status)
  );
  startExecutionButton.disabled = ["queued", "running"].includes(execution.status);
  startExecutionButton.textContent = startExecutionButton.disabled
    ? "Execution in progress"
    : "Start execution";
  executionOutputs.replaceChildren();
  (execution.outputs || []).forEach((cell) => {
    const article = document.createElement("article");
    article.className = "execution-output";
    const heading = document.createElement("h4");
    heading.textContent = `Cell ${cell.cell_number}`;
    article.appendChild(heading);
    (cell.outputs || []).forEach((output) => {
      const pre = document.createElement("pre");
      pre.textContent = output.text || `[${output.output_type || "output"}]`;
      article.appendChild(pre);
    });
    executionOutputs.appendChild(article);
  });
  document.getElementById("execution-logs").textContent = execution.logs || "No runner logs.";
}

loadVerificationExecutionsButton.addEventListener("click", async () => {
  if (!currentNotebookId || !currentNotebookToken) {
    showVerificationStatus("Upload a notebook before loading its saved experiments.", "error");
    return;
  }
  loadVerificationExecutionsButton.disabled = true;
  showVerificationStatus("Loading saved execution records…", "loading");
  try {
    const headers = { Authorization: `Bearer ${currentNotebookToken}` };
    const response = await fetch(
      `${API_BASE_URL}/api/notebooks/${encodeURIComponent(currentNotebookId)}/executions`,
      { headers }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail?.message || "Saved executions could not be loaded.");
    }
    const executions = data.executions || [];
    const originalRuns = executions.filter(
      (item) => item.notebook_id === currentNotebookId && item.notebook_type === "original"
    );
    const correctedRuns = executions.filter(
      (item) => item.notebook_id === correctedNotebookId && item.notebook_type === "corrected"
    );
    populateExecutionOptions(verificationOriginalExecution, originalRuns);
    populateExecutionOptions(verificationCorrectedExecution, correctedRuns);
    updateVerificationButtonState();
    showVerificationStatus(
      `Loaded ${originalRuns.length} original and ${correctedRuns.length} corrected execution record(s).`,
      originalRuns.length && correctedRuns.length ? "success" : "loading"
    );
    const historyResponse = await fetch(
      `${API_BASE_URL}/api/notebooks/${encodeURIComponent(currentNotebookId)}/verifications`,
      { headers }
    );
    const history = await historyResponse.json();
    if (!historyResponse.ok) {
      throw new Error(history?.detail?.message || "Verification history could not be loaded.");
    }
    verificationResults.replaceChildren();
    (history.verifications || []).forEach(renderVerification);
    if (history.verifications?.length) {
      showVerificationStatus(
        `Loaded saved execution records and ${history.verifications.length} prior verification record(s).`,
        "success"
      );
    }
  } catch (error) {
    showVerificationStatus(
      error instanceof Error ? error.message : "Saved verification records could not be loaded.",
      "error"
    );
  } finally {
    loadVerificationExecutionsButton.disabled = false;
  }
});

verificationOriginalExecution.addEventListener("change", updateVerificationButtonState);
verificationCorrectedExecution.addEventListener("change", updateVerificationButtonState);

startVerificationButton.addEventListener("click", async () => {
  if (
    !currentNotebookId ||
    !correctedNotebookId ||
    !currentNotebookToken ||
    !verificationOriginalExecution.value ||
    !verificationCorrectedExecution.value
  ) {
    showVerificationStatus("Select saved executions for both notebook versions.", "error");
    return;
  }
  startVerificationButton.disabled = true;
  showVerificationStatus("Evaluating stored source and execution evidence…", "loading");
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/notebooks/${encodeURIComponent(currentNotebookId)}/verifications`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${currentNotebookToken}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          corrected_notebook_id: correctedNotebookId,
          original_execution_id: verificationOriginalExecution.value,
          corrected_execution_id: verificationCorrectedExecution.value
        })
      }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail?.message || "Repair verification could not be completed.");
    }
    currentVerificationId = data.verification_id;
    renderVerification(data);
    showVerificationStatus(
      `Verification ${data.verification_id} saved. Review each finding and the separate experiment comparison below.`,
      "success"
    );
  } catch (error) {
    showVerificationStatus(
      error instanceof Error ? error.message : "Repair verification could not be completed.",
      "error"
    );
  } finally {
    updateVerificationButtonState();
  }
});

function populateExecutionOptions(select, executions) {
  select.replaceChildren(new Option("Select an execution", ""));
  executions.forEach((execution) => {
    const started = execution.started_at
      ? new Date(execution.started_at).toLocaleString()
      : "start time unavailable";
    const label = `${executionStatusLabel(execution.status)} · ${started} · ${execution.execution_id.slice(0, 8)}`;
    select.add(new Option(label, execution.execution_id));
  });
}

function updateVerificationButtonState() {
  startVerificationButton.disabled = !(
    correctedNotebookId &&
    verificationOriginalExecution.value &&
    verificationCorrectedExecution.value
  );
}

function showVerificationStatus(message, state) {
  verificationStatusMessage.textContent = message;
  verificationStatusMessage.className =
    state === "hidden" ? "graph-status hidden" : `graph-status ${state}`;
}

function verificationStatusLabel(status) {
  return ({
    verified: "Verified",
    partially_verified: "Partially verified",
    not_verified: "Not verified",
    inconclusive: "Inconclusive",
    execution_failed: "Execution failed",
    not_applicable: "Not applicable"
  })[status] || "Unavailable";
}

function renderVerification(report) {
  const article = document.createElement("article");
  article.className = "verification-report workspace-card";
  article.dataset.verificationId = report.verification_id;
  const heading = document.createElement("h3");
  heading.textContent = `Verification · ${report.verified_at ? new Date(report.verified_at).toLocaleString() : "saved record"}`;
  const ids = document.createElement("p");
  ids.className = "finding-meta";
  ids.textContent =
    `Original run ${report.original_execution_id} · Corrected run ${report.corrected_execution_id}`;
  article.append(heading, ids);

  const statusHeading = document.createElement("h4");
  statusHeading.textContent =
    `Original execution: ${executionStatusLabel(report.original_execution_status)} · ` +
    `Corrected execution: ${executionStatusLabel(report.corrected_execution_status)}`;
  article.appendChild(statusHeading);
  (report.findings || []).forEach((item) => article.appendChild(renderVerifiedFinding(item)));
  if (report.comparison) {
    article.appendChild(renderExperimentComparison(report.comparison));
  }
  (report.limitations || []).forEach((limitation) => {
    const note = document.createElement("p");
    note.className = "finding-caveat";
    note.textContent = `Overall limitation: ${limitation}`;
    article.appendChild(note);
  });
  verificationResults.appendChild(article);
}

function renderVerifiedFinding(item) {
  const section = document.createElement("section");
  section.className = "verification-finding";
  const heading = document.createElement("h4");
  heading.textContent = `${item.finding_title} · ${item.finding_id}`;
  const status = document.createElement("span");
  status.className = "verification-status";
  status.dataset.status = item.verification_status;
  status.textContent = verificationStatusLabel(item.verification_status);
  const repair = document.createElement("p");
  repair.className = "finding-meta";
  repair.textContent = `Repair ${item.repair_id} · finding category ${String(item.finding_category || "unknown").replaceAll("_", " ")}`;
  section.append(heading, status, repair);

  const cellActions = document.createElement("div");
  cellActions.className = "verification-cell-links";
  (item.original_cell_references || []).forEach((reference) => {
    if (!Number.isInteger(reference.cell_index)) {
      return;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-button";
    button.textContent = `Open original cell ${reference.cell_index + 1}`;
    button.addEventListener("click", () => {
      selectCell(reference.cell_index);
      window.location.hash = "#cells";
    });
    cellActions.appendChild(button);
  });
  const correctedCells = document.createElement("p");
  correctedCells.className = "finding-meta";
  correctedCells.textContent = `Corrected cell references: ${
    (item.corrected_cell_references || [])
      .map((reference) => Number.isInteger(reference.cell_index) ? reference.cell_index + 1 : "")
      .filter(Boolean)
      .map((index) => `Cell ${index}`)
      .join(", ") || "Not available"
  }`;
  section.append(cellActions, correctedCells);

  const finding = getCurrentFindings().find((candidate) => candidate.id === item.finding_id);
  if (finding) {
    const navigation = document.createElement("div");
    navigation.className = "finding-actions";
    const auditButton = document.createElement("button");
    auditButton.type = "button";
    auditButton.className = "text-button";
    auditButton.textContent = "View finding";
    auditButton.addEventListener("click", () => {
      window.location.hash = "#audit";
      window.requestAnimationFrame(() => {
        document.querySelectorAll(".finding-card").forEach((card) => {
          if (card.dataset.findingId === finding.id) {
            card.scrollIntoView({ behavior: "smooth", block: "center" });
            card.focus?.();
          }
        });
      });
    });
    navigation.appendChild(auditButton);
    const nodeId = finding.related_pipeline_node_ids?.[0];
    if (nodeId) {
      const graphButton = document.createElement("button");
      graphButton.type = "button";
      graphButton.className = "text-button";
      graphButton.textContent = "View pipeline evidence";
      graphButton.addEventListener("click", () => openFindingPipelineNode(finding, nodeId));
      navigation.appendChild(graphButton);
    }
    section.appendChild(navigation);
  }

  appendVerificationList(section, "Checks performed", item.checks_performed, "check");
  appendVerificationList(section, "Evidence", item.evidence, "evidence");
  appendVerificationList(section, "Reasons", item.reasons, "reason");
  appendVerificationList(section, "Remaining risks", item.remaining_risks, "risk");
  appendVerificationList(section, "Limitations", item.limitations, "limitation");
  return section;
}

function appendVerificationList(parent, title, values, className) {
  if (!values?.length) {
    return;
  }
  const heading = document.createElement("h5");
  heading.textContent = title;
  const list = document.createElement("ul");
  list.className = `verification-list verification-${className}`;
  values.forEach((value) => {
    const item = document.createElement("li");
    item.textContent = typeof value === "string" ? value : JSON.stringify(value);
    list.appendChild(item);
  });
  parent.append(heading, list);
}

function renderExperimentComparison(comparison) {
  const section = document.createElement("section");
  section.className = "verification-comparison";
  const heading = document.createElement("h4");
  heading.textContent = "Experiment comparison (separate from repair verification)";
  const comparability = document.createElement("p");
  comparability.className = comparison.comparable
    ? "verification-comparable"
    : "verification-incomparable";
  comparability.textContent = comparison.comparable
    ? "Experimental configurations are comparable based on the recorded checks."
    : "Metric deltas unavailable: comparability was not established.";
  section.append(heading, comparability);

  const executionTable = document.createElement("dl");
  executionTable.className = "execution-metadata";
  [
    ["Original status", comparison.original_execution?.status],
    ["Corrected status", comparison.corrected_execution?.status],
    ["Original duration", formatExecutionDuration(comparison.original_execution?.duration_seconds)],
    ["Corrected duration", formatExecutionDuration(comparison.corrected_execution?.duration_seconds)],
    ["Original cells", comparison.original_execution?.executed_cell_count],
    ["Corrected cells", comparison.corrected_execution?.executed_cell_count]
  ].forEach(([label, value]) => {
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value === undefined || value === null ? "Unavailable" : String(value);
    executionTable.append(term, detail);
  });
  section.appendChild(executionTable);
  appendVerificationList(
    section,
    "Original dataset references",
    comparison.original_execution?.dataset_references,
    "original-datasets"
  );
  appendVerificationList(
    section,
    "Corrected dataset references",
    comparison.corrected_execution?.dataset_references,
    "corrected-datasets"
  );
  appendVerificationList(
    section,
    "Original model, split, and random-seed settings",
    comparison.original_setup ? [comparison.original_setup] : [],
    "original-settings"
  );
  appendVerificationList(
    section,
    "Corrected model, split, and random-seed settings",
    comparison.corrected_setup ? [comparison.corrected_setup] : [],
    "corrected-settings"
  );

  const metrics = comparison.metric_comparisons || [];
  const metricTable = document.createElement("table");
  metricTable.className = "verification-metrics";
  const header = document.createElement("tr");
  ["Metric", "Original", "Corrected", "Corrected − original"].forEach((label) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    header.appendChild(cell);
  });
  const tableHead = document.createElement("thead");
  tableHead.appendChild(header);
  const tableBody = document.createElement("tbody");
  metrics.forEach((metric) => {
    const row = document.createElement("tr");
    [
      metric.name,
      formatMetricValues(metric.original_values, metric.unit) || "Not captured",
      formatMetricValues(metric.corrected_values, metric.unit) || "Not captured",
      metric.comparison_available
        ? formatMetricValues(metric.deltas, metric.unit)
        : "Unavailable"
    ].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = String(value);
      row.appendChild(cell);
    });
    tableBody.appendChild(row);
  });
  metricTable.append(tableHead, tableBody);
  if (metrics.length) {
    section.appendChild(metricTable);
    const metricNote = document.createElement("p");
    metricNote.className = "finding-caveat";
    metricNote.textContent =
      "Metric differences are descriptive only; a higher value does not establish a successful repair or a more reliable model.";
    section.appendChild(metricNote);
  } else {
    const noMetrics = document.createElement("p");
    noMetrics.textContent = "No supported labeled evaluation metrics were captured.";
    section.appendChild(noMetrics);
  }
  appendVerificationList(
    section,
    "Comparability reasons and limitations",
    comparison.comparability_reasons,
    "comparison-reasons"
  );
  appendVerificationList(
    section,
    "Execution configuration differences",
    comparison.setup_differences,
    "configuration-differences"
  );
  return section;
}

function formatExecutionDuration(duration) {
  return typeof duration === "number" ? `${duration.toFixed(2)} seconds` : "Unavailable";
}

function formatMetricValues(values, unit) {
  return (values || [])
    .map((value) => `${value}${unit === "percent" ? "%" : ""}`)
    .join(", ");
}

overlapForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (overlapCheckInProgress) {
    return;
  }
  if (!overlapTrainFile.files[0] || !overlapTestFile.files[0]) {
    showOverlapMessage("Choose both the training and test CSV files.", "error");
    return;
  }

  overlapCheckInProgress = true;
  overlapSubmit.disabled = true;
  overlapSubmit.textContent = "Comparing…";
  overlapResults.replaceChildren();
  showOverlapMessage("Comparing the uploaded split files in memory…", "loading");

  try {
    const formData = new FormData(overlapForm);
    const response = await fetch(`${API_BASE_URL}/api/datasets/overlap`, {
      method: "POST",
      body: formData
    });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("The server returned a non-JSON response.");
    }

    if (!response.ok) {
      const message = response.status >= 500
        ? GENERIC_UPLOAD_ERROR
        : data && data.detail && typeof data.detail.message === "string"
          ? data.detail.message
          : "The uploaded CSV files could not be compared.";
      showOverlapMessage(message, "error");
      return;
    }
    if (!isOverlapSuccessResponse(data)) {
      showOverlapMessage("The server response did not contain valid overlap results.", "error");
      return;
    }

    if (!currentNotebook) {
      showOverlapMessage("Upload a notebook before adding overlap results to its audit.", "error");
      return;
    }
    currentNotebook.analysis.external_dataset_findings = data.overlap.findings;
    renderFindings(getCurrentFindings());
    renderRepairCenter(getCurrentRepairProposals());
    data.overlap.checks.forEach((check) => {
      const item = document.createElement("li");
      item.className = "finding-card";
      item.textContent = check.status === "completed"
        ? `${check.check.replaceAll("_", " ")} · ${check.overlap_count} overlapping value(s)`
        : `${check.check.replaceAll("_", " ")} · skipped: ${check.reason}`;
      overlapResults.appendChild(item);
    });
    const findingCount = data.overlap.findings.length;
    showOverlapMessage(
      findingCount
        ? `Comparison complete. Added ${findingCount} evidence-based dataset finding(s) to this audit.`
        : "Comparison complete. No overlap was detected by the completed checks.",
      "success"
    );
  } catch (error) {
    console.error("Train/test dataset comparison failed.", error);
    showOverlapMessage(GENERIC_UPLOAD_ERROR, "error");
  } finally {
    overlapCheckInProgress = false;
    overlapSubmit.disabled = false;
    overlapSubmit.textContent = "Compare splits";
  }
});

function showUploadMessage(message, state) {
  uploadMessage.textContent = message;
  uploadMessage.className = `upload-message ${state}`;
}

function showDatasetMessage(message, state) {
  datasetUploadMessage.textContent = message;
  datasetUploadMessage.className = `upload-message ${state}`;
}

function showOverlapMessage(message, state) {
  overlapMessage.textContent = message;
  overlapMessage.className = `upload-message ${state}`;
}

function clearDatasetMessage() {
  datasetUploadMessage.textContent = "";
  datasetUploadMessage.className = "upload-message hidden";
}

function resetDatasetAnalysis() {
  clearDatasetMessage();
  datasetResults.classList.add("hidden");
  document.getElementById("dataset-summary").textContent = "";
  datasetColumns.replaceChildren();
}

function clearUploadMessage() {
  uploadMessage.textContent = "";
  uploadMessage.className = "upload-message hidden";
}

function resetRepairWorkflow() {
  repairDecisions = new Map();
  const button = document.getElementById("download-repaired-notebook");
  button.disabled = true;
  button.textContent = "Generate corrected notebook";
  const message = document.getElementById("repair-download-message");
  message.textContent = "";
  message.className = "upload-message hidden";
}

function isNotebookSuccessResponse(data) {
  const notebook = data && data.notebook;
  if (
    !data ||
    data.status !== "success" ||
    !notebook ||
    typeof notebook.filename !== "string" ||
    !notebook.filename ||
    notebook.format_version !== 4 ||
    !["format_version", "total_cells", "code_cells", "markdown_cells", "raw_cells"]
      .every((key) => Number.isInteger(notebook[key]) && notebook[key] >= 0) ||
    !Array.isArray(notebook.cells) ||
    notebook.cells.length !== notebook.total_cells
  ) {
    return false;
  }

  const cellTypes = { code: 0, markdown: 0, raw: 0 };
  const validCells = notebook.cells.every((cell, index) => {
    if (
      !cell ||
      cell.index !== index ||
      !Object.hasOwn(cellTypes, cell.cell_type) ||
      typeof cell.source !== "string" ||
      typeof cell.has_outputs !== "boolean" ||
      (cell.execution_count !== null && !Number.isInteger(cell.execution_count)) ||
      (cell.cell_type !== "code" &&
        (cell.execution_count !== null || cell.has_outputs))
    ) {
      return false;
    }
    cellTypes[cell.cell_type] += 1;
    return true;
  });

  return validCells &&
    notebook.code_cells === cellTypes.code &&
    notebook.markdown_cells === cellTypes.markdown &&
    notebook.raw_cells === cellTypes.raw;
}

function isDatasetSuccessResponse(data) {
  const dataset = data && data.dataset;
  if (
    !data ||
    data.status !== "success" ||
    !dataset ||
    typeof dataset.filename !== "string" ||
    !dataset.filename ||
    !Number.isInteger(dataset.row_count) ||
    dataset.row_count < 0 ||
    !Number.isInteger(dataset.column_count) ||
    dataset.column_count < 0 ||
    !Array.isArray(dataset.columns) ||
    dataset.columns.length !== dataset.column_count
  ) {
    return false;
  }

  const inferredTypes = new Set(["boolean", "empty", "integer", "number", "text"]);
  return dataset.columns.every((column) =>
    column &&
    typeof column.name === "string" &&
    column.name.length > 0 &&
    inferredTypes.has(column.inferred_type) &&
    Number.isInteger(column.non_empty_values) &&
    Number.isInteger(column.missing_values) &&
    column.non_empty_values >= 0 &&
    column.missing_values >= 0 &&
    column.non_empty_values + column.missing_values === dataset.row_count &&
    Number.isFinite(column.missing_percentage) &&
    (column.numeric_summary === null ||
      (column.numeric_summary &&
        Number.isInteger(column.numeric_summary.count) &&
        typeof column.numeric_summary.minimum === "string" &&
        typeof column.numeric_summary.maximum === "string" &&
        typeof column.numeric_summary.mean === "string"))
  );
}

function isOverlapSuccessResponse(data) {
  const overlap = data && data.overlap;
  return Boolean(
    data &&
    data.status === "success" &&
    overlap &&
    Array.isArray(overlap.checks) &&
    Array.isArray(overlap.findings) &&
    overlap.findings.every((finding) =>
      finding &&
      typeof finding.id === "string" &&
      typeof finding.title === "string" &&
      typeof finding.category === "string" &&
      typeof finding.severity === "string" &&
      Array.isArray(finding.evidence)
    )
  );
}

function renderDatasetAnalysis(dataset) {
  document.getElementById("dataset-summary").textContent =
    `${dataset.filename} · ${dataset.row_count} data row(s) · ${dataset.column_count} column(s)`;
  datasetColumns.replaceChildren();

  dataset.columns.forEach((column) => {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    const type = document.createElement("td");
    const missing = document.createElement("td");
    const numeric = document.createElement("td");
    name.textContent = column.name;
    type.textContent = column.inferred_type;
    missing.textContent =
      `${column.missing_values} (${column.missing_percentage}% of rows)`;
    numeric.textContent = column.numeric_summary
      ? `n=${column.numeric_summary.count} · min=${column.numeric_summary.minimum} · max=${column.numeric_summary.maximum} · mean=${column.numeric_summary.mean}`
      : "Not applicable";
    row.append(name, type, missing, numeric);
    datasetColumns.appendChild(row);
  });

  datasetResults.classList.remove("hidden");
}

function showNotebookSummary(notebook) {
  const rows = [
    ["Filename", notebook.filename],
    ["Format version", String(notebook.format_version)],
    ["Total cells", String(notebook.total_cells)],
    ["Code cells", String(notebook.code_cells)],
    ["Markdown cells", String(notebook.markdown_cells)],
    ["Raw cells", String(notebook.raw_cells)]
  ];

  rows.forEach(([key, value]) => {
    const row = document.createElement("tr");
    const label = document.createElement("td");
    const content = document.createElement("td");
    label.textContent = key;
    content.textContent = value;
    row.append(label, content);
    summaryBody.appendChild(row);
  });
}

function renderInvestigation(notebook) {
  const analysis = notebook.analysis;
  if (!analysis || !analysis.pipeline_graph || !Array.isArray(analysis.findings)) {
    return false;
  }

  document.getElementById("analysis-summary").textContent = analysis.analysis_summary;
  document.getElementById("overview-filename").textContent = notebook.filename;
  document.getElementById("overview-format-version").textContent = `nbformat ${notebook.format_version}`;
  const kernel = notebook.metadata?.kernelspec;
  const language = notebook.metadata?.language_info;
  const kernelLabel = kernel?.display_name || kernel?.name;
  const languageLabel = language?.name
    ? `${language.name}${language.version ? ` ${language.version}` : ""}`
    : kernel?.language;
  document.getElementById("overview-kernel-language").textContent =
    [kernelLabel, languageLabel].filter(Boolean).join(" · ") || "Not specified";
  document.getElementById("overview-total-cells").textContent = String(notebook.total_cells);
  document.getElementById("overview-cell-counts").textContent =
    `${notebook.code_cells} / ${notebook.markdown_cells} / ${notebook.raw_cells}`;
  renderLibraries(analysis.libraries || []);
  renderList("imports-list", (analysis.imports || []).map((item) =>
    `${item.module}${item.name !== item.module.split(".")[0] ? ` as ${item.name}` : ""} · cell ${item.cell_index + 1}:${item.line}`
  ), "No import statements recognized.");
  renderList("datasets-list", (analysis.dataset_references || []).map((item) =>
    `${item.operation}("${item.path}") · inferred · cell ${item.cell_index + 1}:${item.line}`
  ), "No recognizable dataset path references found.");

  const operationLabels = {
    data_source: "Data sources",
    feature_engineering: "Feature engineering",
    preprocessing: "Preprocessing",
    split: "Splits",
    model: "Model construction",
    training: "Training calls",
    prediction: "Prediction calls",
    evaluation: "Evaluation calls"
  };
  const operationItems = Object.entries(operationLabels).flatMap(([key, label]) => {
    const items = (analysis.operations && analysis.operations[key]) || [];
    return items.length ? [`${label}: ${items.map((item) => `${item.name} (cell ${item.cell_index + 1}:${item.line})`).join(", ")}`] : [];
  });
  renderList("operations-list", operationItems, "No supported ML operations were recognized.");
  document.getElementById("overview-limitations").textContent =
    (analysis.limitations || []).join(" ");

  analysis.external_dataset_findings = [];
  document.getElementById("finding-severity-filter").value = "all";
  document.getElementById("finding-category-filter").value = "all";
  overlapForm.reset();
  overlapResults.replaceChildren();
  overlapMessage.textContent = "";
  overlapMessage.className = "upload-message hidden";
  renderPipelineTrace(analysis.pipeline_trace);
  renderFindings(getCurrentFindings());
  renderRepairCenter(getCurrentRepairProposals());
  renderOverviewCells(notebook.cells);
  renderCells(notebook.cells);
  return true;
}

function renderLibraries(libraries) {
  const list = document.getElementById("libraries-list");
  list.replaceChildren();
  if (!libraries.length) {
    const empty = document.createElement("li");
    empty.className = "library-empty";
    empty.textContent = "No imported libraries recognized.";
    list.appendChild(empty);
    return;
  }

  libraries.forEach((library) => {
    const item = document.createElement("li");
    const chip = document.createElement("span");
    chip.className = "library-chip";
    chip.textContent = library;
    item.appendChild(chip);
    list.appendChild(item);
  });
}

function renderOverviewCells(cells) {
  const list = document.getElementById("overview-notebook-cells");
  list.replaceChildren();
  cells.forEach((cell) => {
    const item = document.createElement("li");
    item.className = `notebook-cell notebook-cell-${cell.cell_type}`;
    const header = document.createElement("div");
    header.className = "notebook-cell-header";
    const label = document.createElement("strong");
    label.textContent = `Cell ${cell.index + 1} · ${cell.cell_type}`;
    header.appendChild(label);

    if (cell.cell_type === "code") {
      const metadata = document.createElement("span");
      metadata.textContent =
        `Execution count: ${cell.execution_count ?? "not saved"} · Saved outputs: ${cell.has_outputs ? "yes" : "no"}`;
      header.appendChild(metadata);
    }

    const source = document.createElement("pre");
    source.className = "notebook-cell-source";
    source.textContent = cell.source || "(empty cell)";
    const inspect = document.createElement("button");
    inspect.type = "button";
    inspect.className = "text-button notebook-cell-inspect";
    inspect.textContent = "Open in Cell Explorer";
    inspect.addEventListener("click", () => {
      selectCell(cell.index);
      window.location.hash = "#cells";
    });
    item.append(header, source, inspect);
    list.appendChild(item);
  });
}

function renderList(elementId, items, emptyMessage) {
  const list = document.getElementById(elementId);
  list.replaceChildren();
  const values = items.length ? items : [emptyMessage];
  values.forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    list.appendChild(item);
  });
}

function renderGraph(graph, findings) {
  const nodesList = document.getElementById("graph-nodes");
  const edgesList = document.getElementById("graph-edges");
  const unresolvedList = document.getElementById("graph-unresolved");
  const graphSvg = document.getElementById("pipeline-graph");
  const graphViewport = document.getElementById("graph-viewport");
  nodesList.replaceChildren();
  edgesList.replaceChildren();
  unresolvedList.replaceChildren();
  graphSvg.replaceChildren();
  const empty = document.getElementById("graph-empty");
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph.edges) ? graph.edges : [];
  empty.classList.toggle("hidden", nodes.length > 0);
  graphViewport.classList.toggle("hidden", nodes.length === 0);

  const svgNamespace = "http://www.w3.org/2000/svg";
  const nodeSpacing = 204;
  const firstNodeX = 86;
  const nodeY = 82;
  const contentWidth = firstNodeX * 2 + Math.max(0, nodes.length - 1) * nodeSpacing;
  const graphWidth = Math.max(440, graphViewport.clientWidth, contentWidth);
  const nodeOffsetX = (graphWidth - contentWidth) / 2;
  const nodeCenterX = (index) => nodeOffsetX + firstNodeX + index * nodeSpacing;
  graphSvg.setAttribute("viewBox", `0 0 ${graphWidth} 190`);
  graphSvg.setAttribute("width", String(graphWidth));
  graphSvg.setAttribute("height", "190");

  const defs = document.createElementNS(svgNamespace, "defs");
  const marker = document.createElementNS(svgNamespace, "marker");
  marker.setAttribute("id", "pipeline-arrow");
  marker.setAttribute("viewBox", "0 0 10 10");
  marker.setAttribute("refX", "8");
  marker.setAttribute("refY", "5");
  marker.setAttribute("markerWidth", "6");
  marker.setAttribute("markerHeight", "6");
  marker.setAttribute("orient", "auto-start-reverse");
  const arrow = document.createElementNS(svgNamespace, "path");
  arrow.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
  arrow.setAttribute("class", "graph-arrow");
  marker.appendChild(arrow);
  defs.appendChild(marker);
  graphSvg.appendChild(defs);

  const nodeById = new Map(nodes.map((node, index) => [node.id, { node, index }]));
  edges.forEach((edge, edgeIndex) => {
    const source = nodeById.get(edge.source);
    const target = nodeById.get(edge.target);
    if (!source || !target) {
      return;
    }
    const sourceX = nodeCenterX(source.index);
    const targetX = nodeCenterX(target.index);
    const direction = targetX >= sourceX ? 1 : -1;
    const startX = sourceX + direction * 28;
    const endX = targetX - direction * 28;
    const midX = (startX + endX) / 2;
    const path = document.createElementNS(svgNamespace, "path");
    path.setAttribute(
      "d",
      `M ${startX} ${nodeY} C ${midX} 28, ${midX} 28, ${endX} ${nodeY}`
    );
    path.setAttribute("class", "pipeline-edge");
    path.setAttribute("marker-end", "url(#pipeline-arrow)");
    path.dataset.sourceNode = edge.source;
    path.dataset.targetNode = edge.target;
    path.dataset.edgeIndex = String(edgeIndex);
    const edgeTitle = document.createElementNS(svgNamespace, "title");
    edgeTitle.textContent = `${edge.variable}: inferred variable reference`;
    path.appendChild(edgeTitle);
    graphSvg.appendChild(path);

    const edgeLabel = document.createElementNS(svgNamespace, "text");
    edgeLabel.setAttribute("x", String(midX));
    edgeLabel.setAttribute("y", "24");
    edgeLabel.setAttribute("class", "pipeline-edge-label");
    edgeLabel.setAttribute("text-anchor", "middle");
    edgeLabel.textContent = edge.variable;
    graphSvg.appendChild(edgeLabel);
  });

  const findingLocations = new Set(
    findings.flatMap((finding) =>
      (finding.source_refs || []).map((reference) =>
        `${reference.cell_index}:${reference.line}`
      )
    )
  );
  nodes.forEach((node, index) => {
    const centerX = nodeCenterX(index);
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.nodeId = node.id;
    button.dataset.cellIndex = String(node.cell_index);
    const operationLabel = node.label.split(" · cell ")[0];
    button.textContent = `${operationLabel} · cell ${node.cell_index + 1} · line ${node.line} · static source`;
    button.addEventListener("click", () => selectPipelineNode(node.id, node.cell_index));
    item.appendChild(button);
    nodesList.appendChild(item);

    const group = document.createElementNS(svgNamespace, "g");
    group.setAttribute("class", `pipeline-node node-${node.kind}`);
    group.setAttribute("role", "button");
    group.setAttribute("tabindex", "0");
    group.setAttribute("aria-pressed", "false");
    group.setAttribute(
      "aria-label",
      `${operationLabel}, cell ${node.cell_index + 1}, line ${node.line}, static source`
    );
    group.dataset.nodeId = node.id;
    group.dataset.cellIndex = String(node.cell_index);
    group.addEventListener("click", () => selectPipelineNode(node.id, node.cell_index));
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectPipelineNode(node.id, node.cell_index);
      }
    });

    const title = document.createElementNS(svgNamespace, "title");
    title.textContent =
      `${operationLabel} · cell ${node.cell_index + 1}, line ${node.line} · ${node.source || "source not available"}`;
    group.appendChild(title);
    group.appendChild(createNodeShape(svgNamespace, node.kind, centerX, nodeY));

    const label = document.createElementNS(svgNamespace, "text");
    label.setAttribute("x", String(centerX));
    label.setAttribute("y", "143");
    label.setAttribute("class", "pipeline-node-label");
    label.setAttribute("text-anchor", "middle");
    label.textContent = truncateGraphLabel(node.label.split(" · cell ")[0], 23);
    group.appendChild(label);

    const location = document.createElementNS(svgNamespace, "text");
    location.setAttribute("x", String(centerX));
    location.setAttribute("y", "163");
    location.setAttribute("class", "pipeline-node-location");
    location.setAttribute("text-anchor", "middle");
    location.textContent = `cell ${node.cell_index + 1} · line ${node.line}`;
    group.appendChild(location);

    const hasFinding = findingLocations.has(`${node.cell_index}:${node.line}`);
    if (hasFinding) {
      group.dataset.finding = "true";
      group.setAttribute(
        "aria-label",
        `${operationLabel}, cell ${node.cell_index + 1}, line ${node.line}, static source, supported potential finding at this location`
      );
      const markerCircle = document.createElementNS(svgNamespace, "circle");
      markerCircle.setAttribute("cx", String(centerX + 29));
      markerCircle.setAttribute("cy", String(nodeY - 28));
      markerCircle.setAttribute("r", "11");
      markerCircle.setAttribute("class", "finding-marker-bg");
      group.appendChild(markerCircle);
      const cross = document.createElementNS(svgNamespace, "text");
      cross.setAttribute("x", String(centerX + 29));
      cross.setAttribute("y", String(nodeY - 23));
      cross.setAttribute("class", "finding-marker");
      cross.setAttribute("text-anchor", "middle");
      cross.textContent = "×";
      group.appendChild(cross);
    }

    graphSvg.appendChild(group);
  });

  edges.forEach((edge) => {
    const item = document.createElement("li");
    item.className = "graph-edge";
    item.dataset.sourceNode = edge.source;
    item.dataset.targetNode = edge.target;
    const sourceNode = nodes.find((node) => node.id === edge.source);
    const targetNode = nodes.find((node) => node.id === edge.target);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "finding-select";
    button.textContent = `${sourceNode ? sourceNode.label : edge.source} → ${targetNode ? targetNode.label : edge.target} · ${edge.variable}`;
    button.addEventListener("click", () => selectCell(targetNode?.cell_index));
    const tag = document.createElement("span");
    tag.className = "edge-type";
    tag.textContent = edge.relationship.replaceAll("_", " ");
    item.append(button, tag);
    edgesList.appendChild(item);
  });

  if (!edges.length) {
    const item = document.createElement("li");
    item.className = "empty-state";
    item.textContent = "No supported variable-reference connections found.";
    edgesList.appendChild(item);
  }
  renderList(
    "graph-unresolved",
    (graph.unresolved_references || []).map((reference) =>
      `${reference.variable}: ${reference.reason} Cell ${reference.source_ref.cell_index + 1}:${reference.source_ref.line}`
    ),
    "No unresolved variable inputs."
  );
}

function renderWorkflowStages(graph, findings) {
  const stageDefinitions = [
    { title: "Data sources", kinds: ["data_source"] },
    { title: "Feature preparation", kinds: ["feature_engineering", "preprocessing"] },
    { title: "Data split", kinds: ["split"] },
    { title: "Model", kinds: ["model"] },
    { title: "Training", kinds: ["training"] },
    { title: "Prediction", kinds: ["prediction"] },
    { title: "Evaluation", kinds: ["evaluation"] }
  ];
  const stages = stageDefinitions.map((stage) => ({
    ...stage,
    nodes: graph.nodes.filter((node) => stage.kinds.includes(node.kind))
  }));
  const knownKinds = new Set(stageDefinitions.flatMap((stage) => stage.kinds));
  const otherNodes = graph.nodes.filter((node) => !knownKinds.has(node.kind));
  if (otherNodes.length) {
    stages.push({ title: "Other operations", nodes: otherNodes });
  }

  const activeStages = stages.filter((stage) => stage.nodes.length);
  const stageList = document.getElementById("workflow-stages");
  stageList.replaceChildren();
  document.getElementById("workflow-summary").textContent = graph.nodes.length
    ? `${graph.nodes.length} recognized operation${graph.nodes.length === 1 ? "" : "s"} across ${activeStages.length} workflow stage${activeStages.length === 1 ? "" : "s"} · ${graph.edges.length} inferred variable link${graph.edges.length === 1 ? "" : "s"} · ${findings.length} potential finding${findings.length === 1 ? "" : "s"}`
    : "No supported operations were recognized in the notebook source.";

  stages.forEach((stage, index) => {
    const item = document.createElement("li");
    item.className = "workflow-stage";
    item.dataset.active = String(stage.nodes.length > 0);
    item.dataset.stageIndex = String(index);
    item.style.setProperty("--stage-index", String(index));
    const heading = document.createElement("h5");
    heading.textContent = stage.title;
    const count = document.createElement("span");
    count.className = "workflow-stage-count";
    count.textContent = String(stage.nodes.length);
    const operations = document.createElement("ul");
    operations.className = "workflow-stage-operations";

    if (!stage.nodes.length) {
      const empty = document.createElement("li");
      empty.className = "workflow-stage-empty";
      empty.textContent = "Not recognized";
      operations.appendChild(empty);
    } else {
      stage.nodes.forEach((node) => {
        const operationItem = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "workflow-operation";
        const operationLabel = node.label.split(" · cell ")[0];
        button.textContent = `${operationLabel} · cell ${node.cell_index + 1}:${node.line}`;
        button.setAttribute(
          "aria-label",
          `${operationLabel}, cell ${node.cell_index + 1}, line ${node.line}; open source cell`
        );
        button.addEventListener("click", () => {
          selectPipelineNode(node.id, node.cell_index);
        });
        operationItem.appendChild(button);
        operations.appendChild(operationItem);
      });
    }

    item.append(heading, count, operations);
    stageList.appendChild(item);
  });
}

function createNodeShape(svgNamespace, kind, centerX, centerY) {
  let shape;
  if (kind === "data_source") {
    shape = document.createElementNS(svgNamespace, "rect");
    shape.setAttribute("x", String(centerX - 30));
    shape.setAttribute("y", String(centerY - 22));
    shape.setAttribute("width", "60");
    shape.setAttribute("height", "44");
    shape.setAttribute("rx", "9");
  } else if (kind === "split") {
    shape = document.createElementNS(svgNamespace, "path");
    shape.setAttribute(
      "d",
      `M ${centerX} ${centerY - 29} L ${centerX + 37} ${centerY} L ${centerX} ${centerY + 29} L ${centerX - 37} ${centerY} Z`
    );
  } else if (kind === "model") {
    shape = document.createElementNS(svgNamespace, "circle");
    shape.setAttribute("cx", String(centerX));
    shape.setAttribute("cy", String(centerY));
    shape.setAttribute("r", "26");
  } else if (kind === "prediction") {
    shape = document.createElementNS(svgNamespace, "ellipse");
    shape.setAttribute("cx", String(centerX));
    shape.setAttribute("cy", String(centerY));
    shape.setAttribute("rx", "37");
    shape.setAttribute("ry", "24");
  } else if (kind === "feature_engineering" || kind === "preprocessing") {
    shape = document.createElementNS(svgNamespace, "path");
    shape.setAttribute(
      "d",
      `M ${centerX - 29} ${centerY - 21} L ${centerX + 20} ${centerY - 21} L ${centerX + 29} ${centerY + 21} L ${centerX - 20} ${centerY + 21} Z`
    );
  } else if (kind === "evaluation") {
    shape = document.createElementNS(svgNamespace, "path");
    shape.setAttribute(
      "d",
      `M ${centerX - 22} ${centerY - 26} L ${centerX + 22} ${centerY - 26} L ${centerX + 32} ${centerY - 16} L ${centerX + 32} ${centerY + 16} L ${centerX + 22} ${centerY + 26} L ${centerX - 22} ${centerY + 26} L ${centerX - 32} ${centerY + 16} L ${centerX - 32} ${centerY - 16} Z`
    );
  } else {
    shape = document.createElementNS(svgNamespace, "rect");
    shape.setAttribute("x", String(centerX - 34));
    shape.setAttribute("y", String(centerY - 24));
    shape.setAttribute("width", "68");
    shape.setAttribute("height", "48");
    shape.setAttribute("rx", "5");
  }
  shape.setAttribute("class", "pipeline-node-shape");
  return shape;
}

function truncateGraphLabel(label, maxLength) {
  return label.length > maxLength ? `${label.slice(0, maxLength - 1)}…` : label;
}

function selectPipelineNode(nodeId, cellIndex) {
  document.querySelectorAll(".pipeline-node").forEach((node) => {
    const selected = node.dataset.nodeId === nodeId;
    node.dataset.selected = String(selected);
    node.setAttribute("aria-pressed", String(selected));
  });
  document.querySelectorAll("#graph-nodes button").forEach((button) => {
    button.setAttribute("aria-current", String(button.dataset.nodeId === nodeId));
  });
  selectCell(cellIndex);
  window.location.hash = "#cells";
}

const PIPELINE_TYPE_LABELS = {
  dataset_loading: "Dataset loading",
  data_cleaning: "Data cleaning",
  missing_value_handling: "Missing-value handling",
  data_encoding: "Data encoding",
  data_scaling: "Data scaling",
  feature_engineering: "Feature engineering",
  feature_selection: "Feature selection",
  train_test_split: "Train-test split",
  model_initialization: "Model initialization",
  model_training: "Model training",
  prediction: "Prediction",
  model_evaluation: "Model evaluation",
  preprocessing: "Preprocessing",
  unknown: "Unclassified operation"
};
const PIPELINE_STATUS_LABELS = {
  green: "No supported issue detected",
  amber: "Potential finding",
  red: "Confirmed finding",
  grey: "Insufficient evidence"
};

function isValidPipelineTrace(graph) {
  if (
    !graph ||
    !graph.metadata ||
    graph.metadata.trace_type !== "static_source_dependency_graph" ||
    !Array.isArray(graph.nodes) ||
    !Array.isArray(graph.edges) ||
    !Array.isArray(graph.findings) ||
    !Array.isArray(graph.unresolved_references)
  ) {
    return false;
  }
  const nodeIds = new Set();
  for (const node of graph.nodes) {
    if (
      !node ||
      typeof node.id !== "string" ||
      nodeIds.has(node.id) ||
      typeof node.operation_type !== "string" ||
      typeof node.display_label !== "string" ||
      typeof node.operation_name !== "string" ||
      !Number.isInteger(node.cell_index) ||
      !Number.isInteger(node.line) ||
      !Array.isArray(node.input_variables) ||
      !Array.isArray(node.output_variables) ||
      !Array.isArray(node.finding_ids) ||
      !Object.hasOwn(PIPELINE_STATUS_LABELS, node.status)
    ) {
      return false;
    }
    nodeIds.add(node.id);
  }
  const edgeIds = new Set();
  return graph.edges.every((edge) => {
    if (
      !edge ||
      typeof edge.id !== "string" ||
      edgeIds.has(edge.id) ||
      !nodeIds.has(edge.source) ||
      !nodeIds.has(edge.target) ||
      edge.source === edge.target ||
      !Array.isArray(edge.variables) ||
      typeof edge.relationship !== "string" ||
      typeof edge.explanation !== "string"
    ) {
      return false;
    }
    edgeIds.add(edge.id);
    return true;
  });
}

function renderPipelineTrace(graph) {
  const status = document.getElementById("pipeline-status");
  const error = document.getElementById("pipeline-error");
  const empty = document.getElementById("graph-empty");
  const viewport = document.getElementById("graph-viewport");
  const svg = document.getElementById("pipeline-graph");
  status.textContent = "Loading pipeline graph from notebook analysis…";
  error.classList.add("hidden");
  empty.classList.add("hidden");
  svg.replaceChildren();
  currentPipelineTrace = null;
  graphSelectedItem = null;
  graphSelectedFindingId = null;
  graphHighlightFindingPaths = false;
  pipelineGraphLayout = null;
  graphInitialViewBox = null;
  graphViewBox = null;
  document.getElementById("graph-highlight-findings").setAttribute("aria-pressed", "false");
  document.getElementById("graph-finding-filter").value = "all";

  if (!isValidPipelineTrace(graph)) {
    status.textContent = "Pipeline trace unavailable.";
    error.textContent =
      "The notebook analysis did not include a valid pipeline graph. The rest of the notebook analysis is still available.";
    error.classList.remove("hidden");
    viewport.classList.add("hidden");
    document.getElementById("graph-type-filters").replaceChildren();
    document.getElementById("graph-edges").replaceChildren();
    document.getElementById("graph-unresolved").replaceChildren();
    showGraphSelectionEmpty();
    return;
  }

  currentPipelineTrace = graph;
  document.getElementById("graph-type-filters").replaceChildren();
  const types = [...new Set(graph.nodes.map((node) => node.operation_type))].sort();
  types.forEach((type) => {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = type;
    checkbox.checked = true;
    const text = document.createElement("span");
    text.textContent = PIPELINE_TYPE_LABELS[type] || type;
    label.append(checkbox, text);
    document.getElementById("graph-type-filters").appendChild(label);
  });

  renderPipelineEdgeList(graph.edges);
  renderList(
    "graph-unresolved",
    graph.unresolved_references.map((reference) =>
      `${reference.variable}: ${reference.reason} Cell ${reference.source_ref.cell_index + 1}:${reference.source_ref.line}`
    ),
    "No unresolved input variables."
  );
  status.textContent = graph.nodes.length
    ? `${graph.nodes.length} recognized operation(s), ${graph.edges.length} source-supported dependency edge(s).`
    : "Analysis completed; no supported operation was detected.";
  renderPipelineSvg();
}

function renderPipelineEdgeList(edges) {
  const list = document.getElementById("graph-edges");
  list.replaceChildren();
  if (!edges.length) {
    const item = document.createElement("li");
    item.className = "empty-state";
    item.textContent = "No supported operation-to-operation dependencies were identified.";
    list.appendChild(item);
    return;
  }
  const nodes = new Map(currentPipelineTrace.nodes.map((node) => [node.id, node]));
  edges.forEach((edge) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "graph-edge-list-button";
    button.dataset.edgeId = edge.id;
    const source = nodes.get(edge.source);
    const target = nodes.get(edge.target);
    button.textContent =
      `${source ? source.operation_name : edge.source} → ${target ? target.operation_name : edge.target}` +
      (edge.variables.length ? ` · ${edge.variables.join(", ")}` : " · composed estimator");
    item.appendChild(button);
    list.appendChild(item);
  });
}

function visiblePipelineElements() {
  const enabledTypes = new Set(
    [...document.querySelectorAll("#graph-type-filters input:checked")]
      .map((checkbox) => checkbox.value)
  );
  const findingFilter = document.getElementById("graph-finding-filter").value;
  const nodes = currentPipelineTrace.nodes.filter((node) => {
    if (!enabledTypes.has(node.operation_type)) {
      return false;
    }
    if (findingFilter === "findings" && !node.finding_ids.length) {
      return false;
    }
    if (findingFilter === "no-findings" && node.finding_ids.length) {
      return false;
    }
    return true;
  });
  const visibleIds = new Set(nodes.map((node) => node.id));
  const edges = currentPipelineTrace.edges.filter(
    (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)
  );
  return { nodes, edges };
}

function layoutPipelineGraph(nodes, edges) {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const incoming = new Map(nodes.map((node) => [node.id, 0]));
  const outgoing = new Map(nodes.map((node) => [node.id, []]));
  edges.forEach((edge) => {
    incoming.set(edge.target, incoming.get(edge.target) + 1);
    outgoing.get(edge.source).push(edge.target);
  });
  const sourceOrder = (leftId, rightId) => {
    const left = byId.get(leftId);
    const right = byId.get(rightId);
    return left.cell_index - right.cell_index || left.line - right.line || left.id.localeCompare(right.id);
  };
  const queue = [...nodes.filter((node) => incoming.get(node.id) === 0).map((node) => node.id)]
    .sort(sourceOrder);
  const ranks = new Map(nodes.map((node) => [node.id, 0]));
  const visited = new Set();
  while (queue.length) {
    const source = queue.shift();
    visited.add(source);
    outgoing.get(source).forEach((target) => {
      ranks.set(target, Math.max(ranks.get(target), ranks.get(source) + 1));
      incoming.set(target, incoming.get(target) - 1);
      if (incoming.get(target) === 0) {
        queue.push(target);
        queue.sort(sourceOrder);
      }
    });
  }
  nodes.filter((node) => !visited.has(node.id)).forEach((node) => {
    ranks.set(node.id, Math.max(0, node.cell_index));
  });

  const layers = new Map();
  nodes.forEach((node) => {
    const rank = ranks.get(node.id);
    if (!layers.has(rank)) {
      layers.set(rank, []);
    }
    layers.get(rank).push(node);
  });
  const positions = new Map();
  let maxLayerSize = 1;
  [...layers.keys()].sort((a, b) => a - b).forEach((rank) => {
    const layer = layers.get(rank).sort((a, b) =>
      a.cell_index - b.cell_index || a.line - b.line || a.id.localeCompare(b.id)
    );
    maxLayerSize = Math.max(maxLayerSize, layer.length);
    layer.forEach((node, index) => {
      positions.set(node.id, { x: 54 + rank * 250, y: 62 + index * 142 });
    });
  });
  const maxRank = Math.max(0, ...ranks.values());
  return {
    positions,
    width: Math.max(620, 108 + (maxRank + 1) * 250),
    height: Math.max(500, 124 + maxLayerSize * 142)
  };
}

function renderPipelineSvg() {
  if (!currentPipelineTrace) {
    return;
  }
  const svg = document.getElementById("pipeline-graph");
  const viewport = document.getElementById("graph-viewport");
  const empty = document.getElementById("graph-empty");
  const { nodes, edges } = visiblePipelineElements();
  if (!nodes.length) {
    svg.replaceChildren();
    viewport.classList.add("hidden");
    empty.textContent = currentPipelineTrace.nodes.length
      ? "No operations match the selected graph filters."
      : "No supported pipeline operations were identified in this notebook.";
    empty.classList.remove("hidden");
    pipelineGraphLayout = null;
    return;
  }

  viewport.classList.remove("hidden");
  empty.classList.add("hidden");
  pipelineGraphLayout = layoutPipelineGraph(nodes, edges);
  const { width, height, positions } = pipelineGraphLayout;
  const svgNamespace = "http://www.w3.org/2000/svg";
  svg.replaceChildren();
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

  const defs = document.createElementNS(svgNamespace, "defs");
  const marker = document.createElementNS(svgNamespace, "marker");
  marker.setAttribute("id", "pipeline-arrow");
  marker.setAttribute("viewBox", "0 0 10 10");
  marker.setAttribute("refX", "9");
  marker.setAttribute("refY", "5");
  marker.setAttribute("markerWidth", "7");
  marker.setAttribute("markerHeight", "7");
  marker.setAttribute("orient", "auto");
  const arrow = document.createElementNS(svgNamespace, "path");
  arrow.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
  arrow.setAttribute("class", "graph-arrow");
  marker.appendChild(arrow);
  defs.appendChild(marker);
  svg.appendChild(defs);

  const scene = document.createElementNS(svgNamespace, "g");
  scene.setAttribute("class", "graph-scene");
  const visibleIds = new Set(nodes.map((node) => node.id));
  const highlighted = graphHighlightedElements();
  edges.forEach((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    const startX = source.x + 184;
    const startY = source.y + 42;
    const endX = target.x;
    const endY = target.y + 42;
    const controlX = startX + Math.max(38, (endX - startX) / 2);
    const path = document.createElementNS(svgNamespace, "path");
    path.setAttribute(
      "d",
      `M ${startX} ${startY} C ${controlX} ${startY}, ${controlX} ${endY}, ${endX} ${endY}`
    );
    path.setAttribute("class", "pipeline-edge");
    path.setAttribute("marker-end", "url(#pipeline-arrow)");
    path.setAttribute("tabindex", "0");
    path.setAttribute("role", "button");
    path.setAttribute(
      "aria-label",
      `Dependency from ${currentPipelineTrace.nodes.find((node) => node.id === edge.source).operation_name} to ${currentPipelineTrace.nodes.find((node) => node.id === edge.target).operation_name}`
    );
    path.dataset.edgeId = edge.id;
    path.dataset.sourceNode = edge.source;
    path.dataset.targetNode = edge.target;
    path.dataset.relationship = edge.relationship;
    path.dataset.highlighted = String(highlighted.edges.has(edge.id));
    path.dataset.selected = String(
      graphSelectedItem?.type === "edge" && graphSelectedItem.item.id === edge.id
    );
    path.dataset.dimmed = String(highlighted.active && !highlighted.edges.has(edge.id));
    path.addEventListener("click", (event) => {
      event.stopPropagation();
      selectPipelineEdge(edge.id);
    });
    path.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectPipelineEdge(edge.id);
      }
    });
    const title = document.createElementNS(svgNamespace, "title");
    title.textContent = edge.explanation;
    path.appendChild(title);
    scene.appendChild(path);

    if (edge.variables.length) {
      const label = document.createElementNS(svgNamespace, "text");
      label.setAttribute("x", String((startX + endX) / 2));
      label.setAttribute("y", String((startY + endY) / 2 - 7));
      label.setAttribute("class", "pipeline-edge-label");
      label.setAttribute("text-anchor", "middle");
      label.textContent = edge.variables.join(", ");
      scene.appendChild(label);
    }
  });

  nodes.forEach((node) => {
    const point = positions.get(node.id);
    const group = document.createElementNS(svgNamespace, "g");
    group.setAttribute("class", `pipeline-node node-${node.operation_type}`);
    group.setAttribute("role", "button");
    group.setAttribute("tabindex", "0");
    group.setAttribute("aria-pressed", String(
      graphSelectedItem?.type === "node" && graphSelectedItem.item.id === node.id
    ));
    group.setAttribute(
      "aria-label",
      `${node.operation_name}, ${node.display_label}, cell ${node.cell_index + 1}, line ${node.line}; ${PIPELINE_STATUS_LABELS[node.status]}`
    );
    group.dataset.nodeId = node.id;
    group.dataset.cellIndex = String(node.cell_index);
    group.dataset.status = node.status;
    group.dataset.highlighted = String(highlighted.nodes.has(node.id));
    group.dataset.dimmed = String(highlighted.active && !highlighted.nodes.has(node.id));
    group.dataset.selected = String(
      graphSelectedItem?.type === "node" && graphSelectedItem.item.id === node.id
    );
    group.addEventListener("click", () => selectPipelineNodeById(node.id));
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectPipelineNodeById(node.id);
      }
    });
    const title = document.createElementNS(svgNamespace, "title");
    title.textContent = `${node.source}\n${PIPELINE_STATUS_LABELS[node.status]}`;
    group.appendChild(title);

    const shape = document.createElementNS(svgNamespace, "rect");
    shape.setAttribute("x", String(point.x));
    shape.setAttribute("y", String(point.y));
    shape.setAttribute("width", "184");
    shape.setAttribute("height", "84");
    shape.setAttribute("rx", "9");
    shape.setAttribute("class", "pipeline-node-shape");
    group.appendChild(shape);

    const label = document.createElementNS(svgNamespace, "text");
    label.setAttribute("x", String(point.x + 13));
    label.setAttribute("y", String(point.y + 21));
    label.setAttribute("class", "pipeline-node-label");
    label.textContent = node.display_label;
    group.appendChild(label);

    const name = document.createElementNS(svgNamespace, "text");
    name.setAttribute("x", String(point.x + 13));
    name.setAttribute("y", String(point.y + 43));
    name.setAttribute("class", "pipeline-node-name");
    name.textContent = truncateGraphLabel(node.operation_name, 25);
    group.appendChild(name);

    const location = document.createElementNS(svgNamespace, "text");
    location.setAttribute("x", String(point.x + 13));
    location.setAttribute("y", String(point.y + 66));
    location.setAttribute("class", "pipeline-node-location");
    location.textContent = `Cell ${node.cell_index + 1} · line ${node.line}`;
    group.appendChild(location);

    const statusMark = document.createElementNS(svgNamespace, "text");
    statusMark.setAttribute("x", String(point.x + 166));
    statusMark.setAttribute("y", String(point.y + 17));
    statusMark.setAttribute("class", `node-status-mark status-mark-${node.status}`);
    statusMark.textContent = { green: "✓", amber: "!", red: "✕", grey: "?" }[node.status];
    group.appendChild(statusMark);
    scene.appendChild(group);
  });
  svg.appendChild(scene);

  if (!graphInitialViewBox || graphInitialViewBox.width !== width || graphInitialViewBox.height !== height) {
    graphInitialViewBox = { x: 0, y: 0, width, height };
    graphViewBox = { ...graphInitialViewBox };
  } else if (graphViewBox) {
    graphViewBox = { ...graphViewBox };
  }
  updatePipelineViewBox();
  if (graphSelectedItem) {
    renderGraphItemDetails(graphSelectedItem);
  } else {
    showGraphSelectionEmpty();
  }
}

function truncateGraphLabel(label, maxLength) {
  return label.length > maxLength ? `${label.slice(0, maxLength - 1)}…` : label;
}

function graphHighlightedElements() {
  const nodes = new Set();
  const edges = new Set();
  if (graphSelectedItem?.type === "node") {
    const seed = graphSelectedItem.item.id;
    nodes.add(seed);
    traverseGraph(seed, "upstream").forEach((id) => nodes.add(id));
    traverseGraph(seed, "downstream").forEach((id) => nodes.add(id));
    currentPipelineTrace.edges.forEach((edge) => {
      if (nodes.has(edge.source) && nodes.has(edge.target)) {
        edges.add(edge.id);
      }
    });
  } else if (graphSelectedItem?.type === "edge") {
    nodes.add(graphSelectedItem.item.source);
    nodes.add(graphSelectedItem.item.target);
    edges.add(graphSelectedItem.item.id);
  }
  if (graphHighlightFindingPaths) {
    const findingNodes = currentPipelineTrace.nodes.filter((node) =>
      graphSelectedFindingId
        ? node.finding_ids.includes(graphSelectedFindingId)
        : node.finding_ids.length > 0
    );
    findingNodes.forEach((node) => {
      nodes.add(node.id);
      traverseGraph(node.id, "upstream").forEach((id) => nodes.add(id));
    });
    currentPipelineTrace.edges.forEach((edge) => {
      if (nodes.has(edge.source) && nodes.has(edge.target)) {
        edges.add(edge.id);
      }
    });
  }
  const active = Boolean(graphSelectedItem || graphHighlightFindingPaths);
  return { nodes, edges, active };
}

function traverseGraph(startId, direction) {
  const result = new Set();
  const queue = [startId];
  while (queue.length) {
    const current = queue.shift();
    const next = currentPipelineTrace.edges
      .filter((edge) => direction === "upstream" ? edge.target === current : edge.source === current)
      .map((edge) => direction === "upstream" ? edge.source : edge.target);
    next.forEach((id) => {
      if (!result.has(id)) {
        result.add(id);
        queue.push(id);
      }
    });
  }
  return result;
}

function selectPipelineNodeById(nodeId) {
  const node = currentPipelineTrace.nodes.find((candidate) => candidate.id === nodeId);
  if (!node) {
    return;
  }
  graphSelectedItem = { type: "node", item: node };
  renderPipelineSvg();
}

function selectPipelineEdge(edgeId) {
  const edge = currentPipelineTrace?.edges.find((candidate) => candidate.id === edgeId);
  if (!edge) {
    return;
  }
  graphSelectedItem = { type: "edge", item: edge };
  renderPipelineSvg();
}

function showGraphSelectionEmpty() {
  document.getElementById("graph-selection-empty").classList.remove("hidden");
  document.getElementById("graph-node-details").classList.add("hidden");
  document.getElementById("graph-edge-details").classList.add("hidden");
}

function renderGraphItemDetails(selection) {
  document.getElementById("graph-selection-empty").classList.add("hidden");
  const nodeDetails = document.getElementById("graph-node-details");
  const edgeDetails = document.getElementById("graph-edge-details");
  nodeDetails.classList.toggle("hidden", selection.type !== "node");
  edgeDetails.classList.toggle("hidden", selection.type !== "edge");
  if (selection.type === "node") {
    const node = selection.item;
    const edgeMap = currentPipelineTrace.edges;
    const upstream = edgeMap.filter((edge) => edge.target === node.id);
    const downstream = edgeMap.filter((edge) => edge.source === node.id);
    const byId = new Map(currentPipelineTrace.nodes.map((item) => [item.id, item]));
    document.getElementById("graph-node-heading").textContent = node.operation_name;
    document.getElementById("graph-node-type").textContent = node.display_label;
    document.getElementById("graph-node-location").textContent =
      `Cell ${node.cell_index + 1}, line ${node.line}`;
    document.getElementById("graph-node-execution").textContent =
      node.execution_count === null
        ? "No saved execution count"
        : `Saved execution count ${node.execution_count} (metadata only)`;
    document.getElementById("graph-node-evidence").textContent =
      `${PIPELINE_STATUS_LABELS[node.status]} · ${node.evidence_status}`;
    document.getElementById("graph-node-inputs").textContent =
      node.input_variables.join(", ") || "No inputs recognized";
    document.getElementById("graph-node-outputs").textContent =
      node.output_variables.join(", ") || "No outputs recognized";
    document.getElementById("graph-node-upstream").textContent = upstream.length
      ? upstream.map((edge) => byId.get(edge.source)?.operation_name || edge.source).join(", ")
      : "No connected upstream operation";
    document.getElementById("graph-node-downstream").textContent = downstream.length
      ? downstream.map((edge) => byId.get(edge.target)?.operation_name || edge.target).join(", ")
      : "No connected downstream operation";
    const findings = currentPipelineTrace.findings.filter((finding) =>
      node.finding_ids.includes(finding.id)
    );
    document.getElementById("graph-node-findings").textContent = findings.length
      ? findings.map((finding) => `${finding.title} (${finding.status})`).join("; ")
      : "No supported finding at this source location";
    document.getElementById("graph-node-source").textContent = node.source || "Source snippet unavailable.";
    document.getElementById("graph-inspect-source").disabled = !Number.isInteger(node.cell_index);
  } else {
    const edge = selection.item;
    const byId = new Map(currentPipelineTrace.nodes.map((item) => [item.id, item]));
    document.getElementById("graph-edge-source").textContent =
      byId.get(edge.source)?.operation_name || edge.source;
    document.getElementById("graph-edge-target").textContent =
      byId.get(edge.target)?.operation_name || edge.target;
    document.getElementById("graph-edge-variables").textContent =
      edge.variables.join(", ") || "No variable names (pipeline composition)";
    document.getElementById("graph-edge-relationship").textContent =
      edge.relationship.replaceAll("_", " ");
    document.getElementById("graph-edge-confidence").textContent =
      `${edge.dependency_confidence} · ${edge.evidence_status}`;
    document.getElementById("graph-edge-explanation").textContent = edge.explanation;
  }
}

function updatePipelineViewBox() {
  if (!graphViewBox) {
    return;
  }
  document.getElementById("pipeline-graph").setAttribute(
    "viewBox",
    `${graphViewBox.x} ${graphViewBox.y} ${graphViewBox.width} ${graphViewBox.height}`
  );
}

function fitPipelineGraph() {
  if (!pipelineGraphLayout) {
    return;
  }
  const viewport = document.getElementById("graph-viewport");
  const aspect = viewport.clientWidth && viewport.clientHeight
    ? viewport.clientWidth / viewport.clientHeight
    : pipelineGraphLayout.width / pipelineGraphLayout.height;
  const width = Math.max(
    pipelineGraphLayout.width,
    pipelineGraphLayout.height * aspect
  );
  const height = Math.max(
    pipelineGraphLayout.height,
    pipelineGraphLayout.width / aspect
  );
  graphViewBox = {
    x: (pipelineGraphLayout.width - width) / 2,
    y: (pipelineGraphLayout.height - height) / 2,
    width,
    height
  };
  updatePipelineViewBox();
}

function resetPipelineGraph() {
  if (!graphInitialViewBox) {
    return;
  }
  graphViewBox = { ...graphInitialViewBox };
  updatePipelineViewBox();
}

function zoomPipelineGraph(factor) {
  if (!graphViewBox) {
    return;
  }
  const width = graphViewBox.width * factor;
  const height = graphViewBox.height * factor;
  graphViewBox = {
    x: graphViewBox.x + (graphViewBox.width - width) / 2,
    y: graphViewBox.y + (graphViewBox.height - height) / 2,
    width,
    height
  };
  updatePipelineViewBox();
}

function highlightGraphForFinding(finding) {
  if (!currentPipelineTrace) {
    return;
  }
  graphSelectedItem = null;
  graphSelectedFindingId = finding.id;
  graphHighlightFindingPaths = true;
  document.getElementById("graph-highlight-findings").setAttribute("aria-pressed", "true");
  renderPipelineSvg();
  window.location.hash = "#pipeline";
}

function getCurrentFindings() {
  if (!currentNotebook || !currentNotebook.analysis) {
    return [];
  }
  return [
    ...(currentNotebook.analysis.findings || []),
    ...(currentNotebook.analysis.external_dataset_findings || [])
  ];
}

function openFindingPipelineNode(finding, nodeId) {
  if (!currentPipelineTrace || !nodeId) {
    return;
  }
  const node = currentPipelineTrace.nodes.find((item) => item.id === nodeId);
  if (!node) {
    return;
  }
  document.querySelectorAll("#graph-type-filters input").forEach((checkbox) => {
    checkbox.checked = true;
  });
  document.getElementById("graph-finding-filter").value = "all";
  graphSelectedFindingId = finding.id;
  graphHighlightFindingPaths = true;
  document.getElementById("graph-highlight-findings").setAttribute("aria-pressed", "true");
  graphSelectedItem = { type: "node", item: node };
  renderPipelineSvg();
  window.location.hash = "#pipeline";
}

function renderFindings(findings) {
  const list = document.getElementById("findings-list");
  const severityFilter = document.getElementById("finding-severity-filter");
  const categoryFilter = document.getElementById("finding-category-filter");
  const previousCategory = categoryFilter.value;
  const categories = [...new Set(findings.map((finding) => finding.category || "other"))].sort();
  categoryFilter.replaceChildren(new Option("All categories", "all"));
  categories.forEach((category) => {
    categoryFilter.add(new Option(category.replaceAll("_", " "), category));
  });
  categoryFilter.value = categories.includes(previousCategory) ? previousCategory : "all";

  const counts = findings.reduce((totals, finding) => {
    totals[finding.severity] = (totals[finding.severity] || 0) + 1;
    return totals;
  }, {});
  const distribution = Object.entries(counts)
    .map(([severity, count]) => `${count} ${severity}`)
    .join(" · ");
  document.getElementById("findings-summary").textContent =
    `${findings.length} total finding(s)` + (distribution ? ` · ${distribution}` : "");

  const visibleFindings = findings.filter((finding) =>
    (severityFilter.value === "all" || finding.severity === severityFilter.value) &&
    (categoryFilter.value === "all" || finding.category === categoryFilter.value)
  );
  list.replaceChildren();
  document.getElementById("findings-empty").classList.toggle("hidden", visibleFindings.length > 0);

  visibleFindings.forEach((finding) => {
    const item = document.createElement("li");
    item.className = "finding-card";
    item.dataset.findingId = finding.id;
    const heading = document.createElement("h3");
    heading.className = "finding-heading";
    heading.textContent = finding.title;
    const meta = document.createElement("p");
    meta.className = "finding-meta";
    meta.textContent =
      `${finding.category.replaceAll("_", " ")} · ${finding.severity} severity · ` +
      `${finding.confidence} confidence · ${finding.classification.replaceAll("_", " ")}`;
    const description = document.createElement("p");
    description.className = "finding-description";
    description.textContent = finding.description;
    const variables = document.createElement("p");
    variables.className = "finding-meta";
    variables.textContent = `Relevant variables: ${
      (finding.related_variables || []).join(", ") || "Not identified"
    }`;
    const explanation = document.createElement("p");
    explanation.className = "finding-description";
    explanation.textContent = `${finding.risk_explanation || finding.explanation} Recommended correction: ${finding.recommendation}`;
    item.append(heading, meta, description, variables, explanation);

    const evidence = finding.source_code_evidence || finding.evidence || [];
    evidence.forEach((reference) => {
      const evidenceBlock = document.createElement("pre");
      evidenceBlock.className = "finding-evidence";
      if (reference.snippet) {
        evidenceBlock.textContent =
          `Cell ${Number.isInteger(reference.cell_index) ? reference.cell_index + 1 : "dataset"}` +
          `${Number.isInteger(reference.line) ? ` · line ${reference.line}` : ""}\n${reference.snippet}`;
      } else {
        evidenceBlock.textContent = Object.entries(reference)
          .map(([key, value]) => `${key.replaceAll("_", " ")}: ${String(value)}`)
          .join("\n");
      }
      item.appendChild(evidenceBlock);
    });

    const limitations = finding.limitations || (finding.caveat ? [finding.caveat] : []);
    limitations.forEach((limitation) => {
      const caveat = document.createElement("p");
      caveat.className = "finding-caveat";
      caveat.textContent = `Limitation: ${limitation}`;
      item.appendChild(caveat);
    });

    const actions = document.createElement("div");
    actions.className = "finding-actions";
    if ((finding.cell_indices || []).length) {
      const sourceButton = document.createElement("button");
      sourceButton.type = "button";
      sourceButton.className = "finding-select";
      sourceButton.dataset.findingAction = "source";
      sourceButton.dataset.findingId = finding.id;
      sourceButton.textContent =
        `Open source cell${finding.cell_indices.length === 1 ? "" : "s"} ` +
        finding.cell_indices.map((index) => index + 1).join(", ");
      actions.appendChild(sourceButton);
    }
    (finding.related_pipeline_node_ids || []).forEach((nodeId) => {
      const node = currentPipelineTrace?.nodes.find((candidate) => candidate.id === nodeId);
      if (!node) {
        return;
      }
      const nodeButton = document.createElement("button");
      nodeButton.type = "button";
      nodeButton.className = "finding-select";
      nodeButton.dataset.findingAction = "pipeline";
      nodeButton.dataset.findingId = finding.id;
      nodeButton.dataset.nodeId = nodeId;
      nodeButton.textContent = `Open pipeline node · ${node.operation_name}`;
      actions.appendChild(nodeButton);
    });
    if ((finding.related_pipeline_node_ids || []).length) {
      const pathButton = document.createElement("button");
      pathButton.type = "button";
      pathButton.className = "finding-select";
      pathButton.dataset.findingAction = "path";
      pathButton.dataset.findingId = finding.id;
      pathButton.textContent = "Highlight related pipeline path";
      actions.appendChild(pathButton);
    }
    if (actions.childElementCount) {
      item.appendChild(actions);
    }
    list.appendChild(item);
  });
}

function renderRepairCenter(repairs) {
  const list = document.getElementById("repairs-list");
  list.replaceChildren();
  document.getElementById("repair-total-findings").textContent = String(repairs.length);
  document.getElementById("repairable-findings").textContent = String(
    repairs.filter((repair) => repair.repair_status === "automatically_repairable").length
  );
  document.getElementById("manual-findings").textContent = String(
    repairs.filter((repair) => repair.repair_status !== "automatically_repairable").length
  );
  document.getElementById("repairs-empty").classList.toggle("hidden", repairs.length > 0);
  document.getElementById("repairs-status").textContent = repairs.length
    ? "Every finding has a repair classification. Approve only proposals you have reviewed."
    : "No findings were returned by the source analysis.";

  repairs.forEach((repair) => {
    const card = document.createElement("article");
    card.className = "workspace-card repair-card";
    const heading = document.createElement("h3");
    heading.textContent = repair.finding_title || repair.finding_id;
    const status = document.createElement("p");
    status.className = "repair-status";
    status.textContent =
      `${(repair.repair_status || "unknown").replaceAll("_", " ")} · ` +
      `${(repair.validation_status || "not validated").replaceAll("_", " ")}`;
    const category = document.createElement("p");
    category.className = "finding-meta";
    category.textContent =
      `${(repair.finding_category || "other").replaceAll("_", " ")} · ` +
      `cell${repair.affected_cells.length === 1 ? "" : "s"} ` +
      (repair.affected_cells.length
        ? repair.affected_cells.map((index) => index + 1).join(", ")
        : "not identified");
    const explanation = document.createElement("p");
    explanation.className = "finding-description";
    explanation.textContent = repair.explanation || repair.reason || "";
    card.append(heading, status, category, explanation);

    const validation = document.createElement("p");
    validation.className = "finding-caveat";
    validation.textContent = `Validation: ${Object.entries(repair.validation || {})
      .map(([name, value]) => `${name.replaceAll("_", " ")} — ${String(value)}`)
      .join("; ") || "not available"}. Experiment verification was not performed.`;
    card.appendChild(validation);

    (repair.limitations || []).forEach((limitation) => {
      const note = document.createElement("p");
      note.className = "finding-caveat";
      note.textContent = `Limitation: ${limitation}`;
      card.appendChild(note);
    });

    (repair.cell_changes || []).forEach((change) => {
      const originalLabel = document.createElement("h4");
      originalLabel.textContent = `Original code · cell ${change.cell_index + 1}`;
      const original = document.createElement("pre");
      original.className = "repair-code";
      original.textContent = change.original_code;
      const correctedLabel = document.createElement("h4");
      correctedLabel.textContent = `Proposed code · cell ${change.cell_index + 1}`;
      const corrected = document.createElement("pre");
      corrected.className = "repair-code";
      corrected.textContent = change.corrected_code;
      const diffLabel = document.createElement("h4");
      diffLabel.textContent = "Code changes";
      const diff = document.createElement("pre");
      diff.className = "repair-diff";
      diff.textContent = formatRepairDiff(change.original_code, change.corrected_code);
      card.append(originalLabel, original, correctedLabel, corrected, diffLabel, diff);
    });

    if (repair.repair_status === "automatically_repairable") {
      const actions = document.createElement("div");
      actions.className = "finding-actions";
      const decision = repairDecisions.get(repair.repair_id);
      const approve = document.createElement("button");
      approve.type = "button";
      approve.className = "btn";
      approve.dataset.repairAction = "approved";
      approve.dataset.repairId = repair.repair_id;
      approve.textContent = decision === "approved" ? "Approved" : "Approve repair";
      approve.setAttribute("aria-pressed", String(decision === "approved"));
      const reject = document.createElement("button");
      reject.type = "button";
      reject.className = "text-button";
      reject.dataset.repairAction = "rejected";
      reject.dataset.repairId = repair.repair_id;
      reject.textContent = decision === "rejected" ? "Rejected" : "Reject repair";
      reject.setAttribute("aria-pressed", String(decision === "rejected"));
      actions.append(approve, reject);
      card.appendChild(actions);
    }
    list.appendChild(card);
  });

  const approvedCount = [...repairDecisions.values()].filter((item) => item === "approved").length;
  document.getElementById("download-repaired-notebook").disabled = approvedCount === 0;
}

function getCurrentRepairProposals() {
  if (!currentNotebook?.analysis) {
    return [];
  }
  const notebookRepairs = currentNotebook.analysis.repairs || [];
  const datasetRepairs = (currentNotebook.analysis.external_dataset_findings || []).map((finding) => ({
    repair_id: `dataset-${finding.id}`,
    finding_id: finding.id,
    finding_category: finding.category,
    finding_title: finding.title,
    repair_status: "requires_manual_intervention",
    validation_status: "not_applicable",
    affected_cells: [],
    cell_changes: [],
    explanation: "This dataset comparison result is not linked to a notebook split statement. Review the split and entity/group semantics manually.",
    reason: finding.recommendation,
    validation: {
      python_syntax: "not_run",
      variable_references: "not_run",
      finding_pattern: "not_addressed",
      experiment_verification: "not_performed"
    },
    limitations: finding.limitations || []
  }));
  return [...notebookRepairs, ...datasetRepairs];
}

function formatRepairDiff(original, corrected) {
  const before = original.split(/\r?\n/);
  const after = corrected.split(/\r?\n/);
  let prefix = 0;
  while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) {
    prefix += 1;
  }
  let suffix = 0;
  while (
    suffix < before.length - prefix &&
    suffix < after.length - prefix &&
    before[before.length - 1 - suffix] === after[after.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  const removed = before.slice(prefix, before.length - suffix);
  const added = after.slice(prefix, after.length - suffix);
  return [
    ...removed.map((line) => `- ${line}`),
    ...added.map((line) => `+ ${line}`)
  ].join("\n");
}

document.getElementById("download-repaired-notebook").addEventListener("click", async (event) => {
  const message = document.getElementById("repair-download-message");
  const approvedIds = [...repairDecisions.entries()]
    .filter(([, decision]) => decision === "approved")
    .map(([repairId]) => repairId);
  if (!currentNotebookFile || !currentNotebookId || !currentNotebookToken || !approvedIds.length) {
    message.textContent = "Approve at least one repair before generating a notebook.";
    message.className = "upload-message error";
    return;
  }

  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "Generating…";
  message.textContent = "Validating approved changes and generating a separate notebook…";
  message.className = "upload-message loading";
  try {
    const formData = new FormData();
    formData.append("file", currentNotebookFile);
    formData.append("repair_ids", JSON.stringify(approvedIds));
    formData.append("notebook_id", currentNotebookId);
    const response = await fetch(`${API_BASE_URL}/api/notebooks/repairs/generate`, {
      method: "POST",
      headers: { Authorization: `Bearer ${currentNotebookToken}` },
      body: formData
    });
    if (!response.ok) {
      let data = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }
      const errorMessage = data?.detail?.message || "The corrected notebook could not be generated.";
      throw new Error(errorMessage);
    }

    const blob = await response.blob();
    const generatedNotebookId = response.headers.get("X-CodeTrace-Notebook-ID");
    if (!generatedNotebookId) {
      throw new Error("The generated notebook could not be associated with this experiment.");
    }
    correctedNotebookId = generatedNotebookId;
    let correctedOption = executionNotebookSelect.querySelector(
      'option[value="corrected"]'
    );
    if (!correctedOption) {
      correctedOption = new Option("", "corrected");
      executionNotebookSelect.add(correctedOption);
    }
    correctedOption.textContent = "Approved corrected notebook";
    updateVerificationButtonState();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${currentNotebook.filename.replace(/\.ipynb$/i, "")}-repaired.ipynb`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    message.textContent = "Approved corrected notebook generated and downloaded. Starting its experiment still requires an explicit action in Experiments.";
    message.className = "upload-message success";
  } catch (error) {
    message.textContent = error instanceof Error ? error.message : "The corrected notebook could not be generated.";
    message.className = "upload-message error";
  } finally {
    button.textContent = "Generate corrected notebook";
    renderRepairCenter(getCurrentRepairProposals());
  }
});

function renderCells(cells) {
  cellSelector.replaceChildren();
  cells.forEach((cell) => {
    const option = document.createElement("option");
    option.value = String(cell.index);
    option.textContent = `Cell ${cell.index + 1} · ${cell.cell_type}`;
    cellSelector.appendChild(option);
  });
  if (cells.length) {
    selectCell(0);
  } else {
    cellMeta.textContent = "This notebook has no cells.";
    cellSource.textContent = "";
  }
}

function selectCell(index) {
  if (!currentNotebook || !Number.isInteger(index) || !currentNotebook.cells[index]) {
    return;
  }
  const cell = currentNotebook.cells[index];
  cellSelector.value = String(index);
  cellMeta.textContent = `Cell ${cell.index + 1} · ${cell.cell_type}` +
    (cell.cell_type === "code"
      ? ` · execution count: ${cell.execution_count ?? "not saved"} · saved outputs: ${cell.has_outputs ? "yes" : "no"}`
      : "");
  cellSource.textContent = cell.source;
}

generateReportButton.addEventListener("click", async () => {
  if (!currentNotebookId || !currentNotebookToken) {
    showReportStatus("Upload a notebook before generating its report.", "error");
    return;
  }
  generateReportButton.disabled = true;
  generateReportButton.textContent = "Generating…";
  showReportStatus("Collecting saved analysis and workflow records…", "loading");
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/notebooks/${encodeURIComponent(currentNotebookId)}/reports`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${currentNotebookToken}` }
      }
    );
    const report = await response.json();
    if (!response.ok) {
      throw new Error(report?.detail?.message || "The report could not be generated.");
    }
    renderReportCard(report);
    showReportStatus(
      `Report ${report.report_id} saved · ${new Date(report.generated_at).toLocaleString()} · ` +
      `${report.status === "completed" ? "Completed" : "Partially available"}.`,
      report.status === "completed" ? "success" : "loading"
    );
    await loadReportArtifacts();
  } catch (error) {
    showReportStatus(
      error instanceof Error ? error.message : "The report could not be generated.",
      "error"
    );
  } finally {
    generateReportButton.disabled = false;
    generateReportButton.textContent = "Generate report";
  }
});

loadReportsButton.addEventListener("click", async () => {
  await loadSavedReports();
  await loadReportArtifacts();
});

reportList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-report-action]");
  if (!button || !currentNotebookToken) {
    return;
  }
  const reportId = button.dataset.reportId;
  const action = button.dataset.reportAction;
  const format = action === "preview" ? "html" : action;
  const url = `${API_BASE_URL}/api/reports/${encodeURIComponent(reportId)}/${format}`;
  if (action === "preview") {
    button.disabled = true;
    showReportStatus("Loading the saved HTML report preview…", "loading");
    try {
      const response = await fetch(url, {
        headers: { Authorization: `Bearer ${currentNotebookToken}` },
        cache: "no-store"
      });
      if (!response.ok) {
        throw new Error("The HTML report preview is unavailable.");
      }
      reportPreview.srcdoc = await response.text();
      reportPreviewContainer.classList.remove("hidden");
      showReportStatus(`Previewing report ${reportId}.`, "success");
    } catch (error) {
      showReportStatus(
        error instanceof Error ? error.message : "The HTML report preview is unavailable.",
        "error"
      );
    } finally {
      button.disabled = false;
    }
    return;
  }
  const extension = action === "json" ? "evidence.json" : `evidence.${action}`;
  await downloadAuthorizedArtifact(url, `${reportId}.${extension}`);
});

reportArtifactList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-artifact-url]");
  if (!button || !currentNotebookToken) {
    return;
  }
  await downloadAuthorizedArtifact(
    `${API_BASE_URL}${button.dataset.artifactUrl}`,
    button.dataset.filename || "codetrace-artifact.ipynb"
  );
});

async function loadSavedReports() {
  if (!currentNotebookId || !currentNotebookToken) {
    showReportStatus("Upload a notebook before loading its reports.", "error");
    return;
  }
  loadReportsButton.disabled = true;
  showReportStatus("Loading saved report records…", "loading");
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/notebooks/${encodeURIComponent(currentNotebookId)}/reports`,
      { headers: { Authorization: `Bearer ${currentNotebookToken}` } }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail?.message || "Saved reports could not be loaded.");
    }
    reportList.replaceChildren();
    (data.reports || []).slice().reverse().forEach(renderReportCard);
    showReportStatus(
      `${data.reports?.length || 0} saved report(s) for ${currentNotebook.filename}.`,
      "success"
    );
  } catch (error) {
    showReportStatus(
      error instanceof Error ? error.message : "Saved reports could not be loaded.",
      "error"
    );
  } finally {
    loadReportsButton.disabled = false;
  }
}

function renderReportCard(report) {
  const article = document.createElement("article");
  article.className = "workspace-card report-card";
  article.dataset.reportId = report.report_id;
  const heading = document.createElement("h3");
  heading.textContent = `Report · ${report.report_id}`;
  article.appendChild(heading);
  const details = document.createElement("p");
  const notebookName = report.overview?.notebook_name || currentNotebook?.filename || "Notebook";
  const generatedAt = report.generated_at
    ? new Date(report.generated_at).toLocaleString()
    : "timestamp unavailable";
  const state = report.status === "completed" ? "Completed" : "Partially available";
  details.textContent = `${notebookName} · ${generatedAt} · ${state}`;
  article.appendChild(details);
  const actions = document.createElement("div");
  actions.className = "report-actions";
  [
    ["preview", "Preview HTML"],
    ["pdf", "Download PDF"],
    ["html", "Download HTML"],
    ["json", "Download JSON"]
  ].forEach(([action, label]) => {
    const button = document.createElement("button");
    button.className = "btn";
    button.type = "button";
    button.dataset.reportAction = action;
    button.dataset.reportId = report.report_id;
    button.textContent = label;
    actions.appendChild(button);
  });
  article.appendChild(actions);
  reportList.prepend(article);
}

async function loadReportArtifacts() {
  if (!currentNotebookId || !currentNotebookToken) {
    return;
  }
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/notebooks/${encodeURIComponent(currentNotebookId)}/artifacts`,
      { headers: { Authorization: `Bearer ${currentNotebookToken}` } }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail?.message || "Notebook artifacts could not be loaded.");
    }
    reportArtifactList.replaceChildren();
    const artifacts = [
      ...(data.notebooks || []).map((item) => ({
        ...item,
        label: `${item.notebook_type === "original" ? "Original" : "Corrected"} notebook · ${item.filename}`
      })),
      ...(data.datasets || []).map((item) => ({
        ...item,
        label: `Associated dataset · ${item.filename}`
      })),
      ...(data.executed_notebooks || []).map((item) => ({
        ...item,
        label: `Executed notebook · ${item.filename} · ${item.execution_id.slice(0, 8)}`
      }))
    ];
    if (!artifacts.length) {
      reportArtifactList.textContent = "No notebook artifacts are available.";
      return;
    }
    artifacts.forEach((artifact) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "text-button";
      button.dataset.artifactUrl = artifact.download_path;
      button.dataset.filename = artifact.filename;
      button.textContent = `Download ${artifact.label}`;
      reportArtifactList.appendChild(button);
    });
  } catch (error) {
    reportArtifactList.textContent =
      error instanceof Error ? error.message : "Notebook artifacts could not be loaded.";
  }
}

async function downloadAuthorizedArtifact(url, filename) {
  if (!currentNotebookToken) {
    showReportStatus("The notebook access token is unavailable. Upload the notebook again.", "error");
    return;
  }
  showReportStatus(`Preparing ${filename}…`, "loading");
  try {
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${currentNotebookToken}` },
      cache: "no-store"
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data?.detail?.message || `Download failed (${response.status}).`);
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename.replace(/[\\/:*?"<>|]/g, "_");
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    showReportStatus(`Downloaded ${filename}.`, "success");
  } catch (error) {
    showReportStatus(
      error instanceof Error ? error.message : `Download failed for ${filename}.`,
      "error"
    );
  }
}

function showReportStatus(message, state) {
  reportStatusMessage.textContent = message;
  reportStatusMessage.className =
    state === "hidden" ? "graph-status hidden" : `graph-status ${state}`;
}
