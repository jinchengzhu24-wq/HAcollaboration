const state = {
  sessionId: null,
  planConfirmed: false,
  currentQuestions: [],
  awaitingDocumentReview: false,
  activeStageNumber: null,
  completedStageCount: 0,
  currentDocument: null,
  stageDocuments: [],
  isComplete: false,
  editorDirty: false,
  selectedDocumentStageIndex: null,
  latestDocumentStageIndex: null,
};

const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const projectTitleInput = document.getElementById("project-title");
const chatFeed = document.getElementById("chat-feed");
const confirmPlanButton = document.getElementById("confirm-plan");
const toggleAdjustButton = document.getElementById("toggle-adjust");
const submitAdjustmentButton = document.getElementById("submit-adjustment");
const saveDocButton = document.getElementById("save-doc-button");
const continueStageButton = document.getElementById("continue-stage-button");
const docPreviewInput = document.getElementById("doc-preview");
const docSelector = document.getElementById("doc-selector");
const docUploadInput = document.getElementById("doc-upload");

chatForm.addEventListener("submit", handleChatSubmit);
confirmPlanButton.addEventListener("click", handleConfirmPlan);
toggleAdjustButton.addEventListener("click", toggleAdjustmentBox);
submitAdjustmentButton.addEventListener("click", handleAdjustPlan);
saveDocButton.addEventListener("click", handleSaveEditorChanges);
continueStageButton.addEventListener("click", handleContinueStage);
chatInput.addEventListener("input", autoGrowComposer);
docPreviewInput.addEventListener("input", handleEditorInput);
docSelector.addEventListener("change", handleDocumentSelectionChange);
docUploadInput.addEventListener("change", handleUploadDocument);

async function handleChatSubmit(event) {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  if (!state.sessionId) {
    await createSession(message);
    return;
  }

  if (!state.planConfirmed) {
    window.alert("Please confirm the stage plan first, or submit a revision request.");
    return;
  }

  if (state.awaitingDocumentReview) {
    window.alert("Please review the current stage document on the right before continuing.");
    return;
  }

  await submitTurn(message);
}

async function createSession(initialIdea) {
  appendBubble("user", initialIdea);
  clearComposer();
  removeEmptyState();

  try {
    const response = await fetch("/dialogue/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        initial_idea: initialIdea,
        project_title: projectTitleInput.value.trim() || null,
      }),
    });
    if (!response.ok) throw new Error("Failed to create session");

    const data = await response.json();
    applySessionState(data);
    updateMeta(data.llm_status, data.current_round_label, data.remaining_rounds);
    updateQuestionChip("Review the stage plan on the left, then confirm or revise it.");
    updateStagePlan(data.stage_plan);
    updateDocumentPanel();
    showPlanPanel(true);
    appendBubble("ai", data.opening_message);
  } catch (error) {
    appendBubble("ai", `Error while creating the session: ${error.message}`);
  }
}

async function handleConfirmPlan() {
  if (!state.sessionId) return;

  try {
    const response = await fetch(`/dialogue/sessions/${state.sessionId}/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmed: true }),
    });
    if (!response.ok) throw new Error("Failed to confirm the plan");

    const data = await response.json();
    applyPlanState(data);
    updateMeta(
      document.getElementById("llm-status").textContent,
      data.current_round_label,
      data.remaining_rounds,
    );
    updateStagePlan(data.stage_plan);
    updateDocumentPanel();
    updateQuestionChip(formatQuestions(data.current_questions));
    appendBubble("ai", `${data.message}\n\nQuestions for this stage:\n${formatQuestions(data.current_questions, true)}`);
    showPlanPanel(false);
  } catch (error) {
    appendBubble("ai", `Plan confirmation failed: ${error.message}`);
  }
}

async function handleAdjustPlan() {
  if (!state.sessionId) return;

  const adjustmentText = document.getElementById("adjustment-text").value.trim();
  if (!adjustmentText) {
    window.alert("Please describe how you want the stage plan to change.");
    return;
  }

  appendBubble("user", `I want to revise the stage plan:\n${adjustmentText}`);

  try {
    const response = await fetch(`/dialogue/sessions/${state.sessionId}/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        confirmed: false,
        adjustment_text: adjustmentText,
      }),
    });
    if (!response.ok) throw new Error("Failed to revise the plan");

    const data = await response.json();
    applyPlanState(data);
    updateMeta(
      document.getElementById("llm-status").textContent,
      data.current_round_label,
      data.remaining_rounds,
    );
    updateStagePlan(data.stage_plan);
    updateDocumentPanel();
    updateQuestionChip(formatQuestions(data.current_questions));
    appendBubble("ai", `${data.message}\n\nQuestions for this stage:\n${formatQuestions(data.current_questions, true)}`);
    document.getElementById("adjustment-text").value = "";
    document.getElementById("adjustment-box").classList.add("hidden");
    showPlanPanel(false);
  } catch (error) {
    appendBubble("ai", `Plan revision failed: ${error.message}`);
  }
}

async function submitTurn(rawMessage) {
  appendBubble("user", rawMessage);
  clearComposer();
  const parsed = parseUserReply(rawMessage);

  try {
    const response = await fetch(`/dialogue/sessions/${state.sessionId}/turn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        answers: parsed.answers,
        latest_input: parsed.latestInput,
      }),
    });
    if (!response.ok) throw new Error("Failed to submit this stage response");

    const data = await response.json();
    applyTurnState(data);
    updateMeta(
      document.getElementById("llm-status").textContent,
      data.current_round_label,
      data.remaining_rounds,
    );
    updateStagePlan();
    updateDocumentPanel();

    const aiMessage = [
      data.message,
      "",
      "Stage Feedback:",
      data.stage_feedback,
      "",
      "Guidance:",
      data.guidance,
      "",
      "Stage Draft:",
      data.draft,
    ].join("\n");
    appendBubble("ai", aiMessage);

    if (data.is_complete) {
      updateQuestionChip("All stages are complete.");
      appendBubble("ai", `Final Summary:\n${data.final_summary || ""}`);
      return;
    }

    if (data.awaiting_document_review) {
      updateQuestionChip("Review the docx on the right, then continue to the next stage.");
    } else {
      updateQuestionChip(formatQuestions(data.next_questions));
    }
  } catch (error) {
    appendBubble("ai", `Stage submission failed: ${error.message}`);
  }
}

async function handleUploadDocument() {
  const selectedDoc = getSelectedDocument();
  if (!state.sessionId || !selectedDoc) return;

  if (!docUploadInput.files || !docUploadInput.files.length) {
    return;
  }

  const formData = new FormData();
  formData.append("file", docUploadInput.files[0]);

  try {
    const response = await fetch(
      `/dialogue/sessions/${state.sessionId}/documents/${selectedDoc.stage_index}/upload`,
      { method: "POST", body: formData },
    );
    if (!response.ok) throw new Error("Failed to upload the revised document");

    const data = await response.json();
    syncDocumentState(data.current_document, data.stage_documents || [], {
      preserveSelection: true,
      selectedStageIndex: selectedDoc.stage_index,
    });
    updateDocumentPanel();
    appendBubble("ai", data.message);
    docUploadInput.value = "";
  } catch (error) {
    appendBubble("ai", `Document upload failed: ${error.message}`);
    docUploadInput.value = "";
  }
}

async function handleContinueStage() {
  if (!state.sessionId) return;
  if (state.editorDirty) {
    window.alert("Please save your editor changes before continuing.");
    return;
  }
  if (!isLatestDocumentSelected()) {
    window.alert("Please switch back to the latest stage document before continuing.");
    return;
  }

  try {
    const response = await fetch(`/dialogue/sessions/${state.sessionId}/continue`, {
      method: "POST",
    });
    if (!response.ok) throw new Error("Failed to continue to the next stage");

    const data = await response.json();
    state.awaitingDocumentReview = data.awaiting_document_review;
    state.activeStageNumber = data.active_stage_number;
    state.completedStageCount = data.completed_stage_count;
    state.currentQuestions = data.current_questions || [];
    syncDocumentState(data.current_document, data.stage_documents || []);

    updateMeta(
      document.getElementById("llm-status").textContent,
      data.current_round_label,
      data.remaining_rounds,
    );
    updateStagePlan();
    updateDocumentPanel();
    updateQuestionChip(formatQuestions(data.current_questions));
    appendBubble("ai", `${data.message}\n\nQuestions for this stage:\n${formatQuestions(data.current_questions, true)}`);
  } catch (error) {
    appendBubble("ai", `Could not continue: ${error.message}`);
  }
}

async function handleSaveEditorChanges() {
  const selectedDoc = getSelectedDocument();
  if (!state.sessionId || !selectedDoc) return;

  const content = docPreviewInput.value.trim();
  if (!content) {
    window.alert("The document editor cannot be empty.");
    return;
  }

  try {
    const response = await fetch(
      `/dialogue/sessions/${state.sessionId}/documents/${selectedDoc.stage_index}/edit`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    );
    if (!response.ok) throw new Error("Failed to save the editor changes");

    const data = await response.json();
    syncDocumentState(data.current_document, data.stage_documents || [], {
      preserveSelection: true,
      selectedStageIndex: selectedDoc.stage_index,
    });
    state.editorDirty = false;
    updateDocumentPanel();
    appendBubble("ai", data.message);
  } catch (error) {
    appendBubble("ai", `Saving editor changes failed: ${error.message}`);
  }
}

function applySessionState(data) {
  state.sessionId = data.session_id;
  state.planConfirmed = data.plan_confirmed;
  state.currentQuestions = data.current_questions || [];
  state.awaitingDocumentReview = data.awaiting_document_review;
  state.activeStageNumber = data.active_stage_number;
  state.completedStageCount = data.completed_stage_count || 0;
  state.isComplete = data.is_complete;
  syncDocumentState(data.current_document, data.stage_documents || []);
}

function applyPlanState(data) {
  state.planConfirmed = data.plan_confirmed;
  state.currentQuestions = data.current_questions || [];
  state.awaitingDocumentReview = data.awaiting_document_review;
  state.activeStageNumber = data.active_stage_number;
  state.completedStageCount = data.completed_stage_count || 0;
  syncDocumentState(data.current_document, data.stage_documents || []);
}

function applyTurnState(data) {
  state.currentQuestions = data.next_questions || [];
  state.awaitingDocumentReview = data.awaiting_document_review;
  state.activeStageNumber = data.active_stage_number;
  state.completedStageCount = data.completed_stage_count || 0;
  state.isComplete = data.is_complete;
  syncDocumentState(data.current_document, data.stage_documents || []);
}

function updateMeta(llmStatus, roundLabel, remainingRounds) {
  document.getElementById("llm-status").textContent = llmStatus;
  document.getElementById("round-label").textContent = roundLabel;
  document.getElementById("rounds-left").textContent = String(remainingRounds);
}

function updateStagePlan(stagePlan = null) {
  const stageList = document.getElementById("stage-plan");

  if (Array.isArray(stagePlan) && stagePlan.length) {
    stageList.innerHTML = "";
    stagePlan.forEach((stage) => {
      const item = document.createElement("li");
      item.className = "stage-item pending";
      item.dataset.index = String(stage.index);
      item.innerHTML = `
        <div class="stage-index">${stage.index}</div>
        <div class="stage-content">
          <p class="stage-label">${stage.label}</p>
          <p class="stage-reason">${stage.reason}</p>
        </div>
      `;
      stageList.appendChild(item);
    });
  }

  const items = Array.from(stageList.querySelectorAll(".stage-item"));
  items.forEach((item) => {
    const index = Number(item.dataset.index || 0);
    item.classList.remove("active", "completed", "pending");

    if (state.isComplete || index <= state.completedStageCount) {
      item.classList.add("completed");
    } else if (state.activeStageNumber === index) {
      item.classList.add("active");
    } else {
      item.classList.add("pending");
    }
  });

  const total = items.length;
  const summary = document.getElementById("stage-summary");
  if (!total) {
    summary.textContent = "Waiting for stage planning";
  } else if (state.isComplete) {
    summary.textContent = "Completed";
  } else if (state.awaitingDocumentReview) {
    summary.textContent = `Completed ${state.completedStageCount}/${total}, waiting for doc review`;
  } else if (state.activeStageNumber) {
    summary.textContent = `Stage ${state.activeStageNumber} of ${total}`;
  } else {
    summary.textContent = `${total} stages`;
  }
}

function updateQuestionChip(text) {
  document.getElementById("question-chip").textContent = text;
}

function updateDocumentPanel() {
  const doc = getSelectedDocument();
  const latestDoc = getLatestDocument();
  const latestSelected = isLatestDocumentSelected();
  const downloadLink = document.getElementById("download-doc");
  const uploadInput = document.getElementById("doc-upload");
  const editorStatus = document.getElementById("doc-editor-status");

  document.getElementById("doc-status-pill").textContent = doc
    ? !latestSelected && latestDoc
      ? "History"
      : doc.is_modified
        ? "Revised"
        : doc.source === "uploaded"
          ? "Uploaded"
          : "Ready"
    : "Not Ready";

  docPreviewInput.value = doc?.preview_text || "No document content yet.";
  docPreviewInput.readOnly = !doc;

  if (doc?.download_url) {
    downloadLink.href = doc.download_url;
    downloadLink.classList.remove("disabled");
  } else {
    downloadLink.href = "#";
    downloadLink.classList.add("disabled");
  }

  continueStageButton.disabled = !state.awaitingDocumentReview || !latestSelected;
  saveDocButton.disabled = !doc;
  uploadInput.disabled = !doc;
  editorStatus.textContent = buildEditorStatus(doc, latestSelected);
  renderDocumentSelector();
}

function syncDocumentState(currentDocument, stageDocuments, options = {}) {
  state.stageDocuments = Array.isArray(stageDocuments) ? stageDocuments : [];
  state.currentDocument = resolveLatestDocument(currentDocument, state.stageDocuments);
  state.latestDocumentStageIndex = state.currentDocument?.stage_index ?? null;

  const preferredStageIndex = options.selectedStageIndex ?? null;
  const hasPreferredSelection = preferredStageIndex !== null && state.stageDocuments.some(
    (doc) => doc.stage_index === preferredStageIndex,
  );
  const hasCurrentSelection = options.preserveSelection && state.selectedDocumentStageIndex !== null
    && state.stageDocuments.some((doc) => doc.stage_index === state.selectedDocumentStageIndex);

  if (hasPreferredSelection) {
    state.selectedDocumentStageIndex = preferredStageIndex;
  } else if (hasCurrentSelection) {
    state.selectedDocumentStageIndex = state.selectedDocumentStageIndex;
  } else {
    state.selectedDocumentStageIndex = state.latestDocumentStageIndex;
  }

  state.editorDirty = false;
}

function renderDocumentSelector() {
  if (!state.stageDocuments.length) {
    docSelector.innerHTML = `<option value="">No documents yet</option>`;
    docSelector.disabled = true;
    return;
  }

  docSelector.disabled = false;
  docSelector.innerHTML = state.stageDocuments
    .map((doc) => {
      const suffix = doc.is_modified ? " (Revised)" : "";
      const selected = doc.stage_index === state.selectedDocumentStageIndex ? " selected" : "";
      return `<option value="${doc.stage_index}"${selected}>Stage ${doc.stage_index} - ${doc.stage_label}${suffix}</option>`;
    })
    .join("");
}

function handleDocumentSelectionChange(event) {
  const stageIndex = Number(event.target.value);

  if (!Number.isFinite(stageIndex) || stageIndex === state.selectedDocumentStageIndex) {
    renderDocumentSelector();
    return;
  }

  if (state.editorDirty) {
    const shouldSwitch = window.confirm(
      "You have unsaved editor changes. Switch documents without saving?",
    );
    if (!shouldSwitch) {
      renderDocumentSelector();
      return;
    }
  }

  state.selectedDocumentStageIndex = stageIndex;
  state.editorDirty = false;
  updateDocumentPanel();
}

function buildEditorStatus(doc, latestSelected) {
  if (!doc) return "Read only";
  if (state.editorDirty) return "Unsaved changes";
  if (!latestSelected) return "Viewing earlier stage";
  return "Editable";
}

function resolveLatestDocument(currentDocument, stageDocuments) {
  if (Array.isArray(stageDocuments) && stageDocuments.length) {
    return stageDocuments[stageDocuments.length - 1];
  }
  return currentDocument || null;
}

function getLatestDocument() {
  if (state.latestDocumentStageIndex === null) return null;
  return state.stageDocuments.find((doc) => doc.stage_index === state.latestDocumentStageIndex) || null;
}

function getSelectedDocument() {
  if (state.selectedDocumentStageIndex === null) return null;
  return state.stageDocuments.find((doc) => doc.stage_index === state.selectedDocumentStageIndex) || null;
}

function isLatestDocumentSelected() {
  return (
    state.selectedDocumentStageIndex !== null
    && state.latestDocumentStageIndex !== null
    && state.selectedDocumentStageIndex === state.latestDocumentStageIndex
  );
}

function appendBubble(role, content) {
  removeEmptyState();
  const template = document.getElementById("bubble-template");
  const node = template.content.firstElementChild.cloneNode(true);
  node.classList.add(role === "user" ? "user" : "ai");
  node.querySelector(".bubble").textContent = content;
  chatFeed.appendChild(node);
  chatFeed.scrollTop = chatFeed.scrollHeight;
}

function parseUserReply(rawMessage) {
  const blocks = rawMessage
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean);

  if (blocks.length === 0) return { answers: [rawMessage], latestInput: null };
  if (blocks.length === 1) return { answers: [blocks[0]], latestInput: null };
  if (blocks.length === 2) return { answers: [blocks[0], blocks[1]], latestInput: null };

  return {
    answers: [blocks[0], blocks[1]],
    latestInput: blocks.slice(2).join("\n\n"),
  };
}

function formatQuestions(questions, withLineBreak = false) {
  if (!questions || !questions.length) return "There are no pending questions right now.";
  const lines = questions.map((question, index) => `${index + 1}. ${question}`);
  return lines.join(withLineBreak ? "\n" : " | ");
}

function showPlanPanel(visible) {
  document.getElementById("plan-panel").classList.toggle("hidden", !visible);
}

function toggleAdjustmentBox() {
  document.getElementById("adjustment-box").classList.toggle("hidden");
}

function autoGrowComposer() {
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 180)}px`;
}

function clearComposer() {
  chatInput.value = "";
  chatInput.style.height = "auto";
}

function handleEditorInput() {
  if (!getSelectedDocument()) return;
  state.editorDirty = true;
  document.getElementById("doc-editor-status").textContent = "Unsaved changes";
}

function removeEmptyState() {
  const emptyState = chatFeed.querySelector(".empty-state");
  if (emptyState) emptyState.remove();
}
