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
let currentNotebook = null;
let healthCheckInProgress = false;
let uploadInProgress = false;

cellSelector.addEventListener("change", () => selectCell(Number(cellSelector.value)));

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
  const validWorkspaceRoutes = ["summary", "overview", "pipeline", "audit", "cells", "evidence"];
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

    if (!isNotebookSuccessResponse(data)) {
      showUploadMessage("The server response did not contain a valid notebook summary.", "error");
      return;
    }

    currentNotebook = data.notebook;
    showNotebookSummary(data.notebook);
    if (!renderInvestigation(data.notebook)) {
      currentNotebook = null;
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
  currentNotebook = null;
  uploadForm.reset();
  clearUploadMessage();
  notebookSummary.classList.add("hidden");
  workspace.classList.add("hidden");
  uploadStage.classList.remove("hidden");
  window.location.hash = "#inspect";
  showRoute();
  notebookFile.focus();
});

function showUploadMessage(message, state) {
  uploadMessage.textContent = message;
  uploadMessage.className = `upload-message ${state}`;
}

function clearUploadMessage() {
  uploadMessage.textContent = "";
  uploadMessage.className = "upload-message hidden";
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

  renderGraph(analysis.pipeline_graph, analysis.findings);
  renderWorkflowStages(analysis.pipeline_graph, analysis.findings);
  renderFindings(analysis.findings);
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

function renderFindings(findings) {
  const list = document.getElementById("findings-list");
  list.replaceChildren();
  document.getElementById("findings-empty").classList.toggle("hidden", findings.length > 0);

  findings.forEach((finding) => {
    const item = document.createElement("li");
    item.className = "finding-card";
    const heading = document.createElement("h3");
    heading.className = "finding-heading";
    heading.textContent = finding.title;
    const meta = document.createElement("p");
    meta.className = "finding-meta";
    meta.textContent = `${finding.severity} severity · ${finding.confidence} confidence · potential risk`;
    const description = document.createElement("p");
    description.className = "finding-description";
    description.textContent = finding.description;
    const explanation = document.createElement("p");
    explanation.className = "finding-description";
    explanation.textContent = `${finding.explanation} Recommendation: ${finding.recommendation}`;
    const caveat = document.createElement("p");
    caveat.className = "finding-caveat";
    caveat.textContent = `Limitation: ${finding.caveat}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "finding-select";
    button.textContent = `Inspect evidence in cell${finding.cell_indices.length === 1 ? "" : "s"} ${finding.cell_indices.map((index) => index + 1).join(", ")}`;
    button.addEventListener("click", () => {
      highlightGraphForFinding(finding);
      selectCell(finding.cell_indices[0]);
      window.location.hash = "#cells";
    });
    item.append(heading, meta, description, explanation, caveat, button);
    list.appendChild(item);
  });
}

function highlightGraphForFinding(finding) {
  const related = new Set(finding.cell_indices.map((index) => String(index)));
  const relatedNodeIds = new Set();
  document.querySelectorAll("#graph-nodes button").forEach((button) => {
    const selected = related.has(button.dataset.cellIndex);
    button.setAttribute("aria-current", String(selected));
    if (selected) {
      relatedNodeIds.add(button.dataset.nodeId);
    }
  });
  document.querySelectorAll(".pipeline-node").forEach((node) => {
    node.dataset.highlighted = String(related.has(node.dataset.cellIndex));
  });
  document.querySelectorAll(".graph-edge").forEach((edge) => {
    const nodeIds = new Set(
      [...document.querySelectorAll("#graph-nodes button")]
        .filter((button) => related.has(button.dataset.cellIndex))
        .map((button) => button.dataset.nodeId)
    );
    edge.dataset.highlighted = String(
      nodeIds.has(edge.dataset.sourceNode) || nodeIds.has(edge.dataset.targetNode)
    );
  });
  document.querySelectorAll(".pipeline-edge").forEach((edge) => {
    edge.dataset.highlighted = String(
      relatedNodeIds.has(edge.dataset.sourceNode) ||
      relatedNodeIds.has(edge.dataset.targetNode)
    );
  });
}

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

document.getElementById("download-report").addEventListener("click", () => {
  if (!currentNotebook || !currentNotebook.analysis) {
    return;
  }
  const report = {
    notebook: currentNotebook,
    findings: currentNotebook.analysis.findings,
    confidence_definitions: currentNotebook.analysis.confidence_definitions,
    severity_definitions: currentNotebook.analysis.severity_definitions,
    limitations: currentNotebook.analysis.limitations
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const safeName = currentNotebook.filename.replace(/[^a-z0-9._-]/gi, "_");
  link.href = url;
  link.download = `${safeName}.evidence.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
});
