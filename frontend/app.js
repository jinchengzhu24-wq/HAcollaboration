const state = {
  sessionId: null,
  planConfirmed: false,
  fullStagePlan: [],
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
const chatFeed = document.getElementById("chat-feed");
const saveDocButton = document.getElementById("save-doc-button");
const continueStageButton = document.getElementById("continue-stage-button");
const docPreviewInput = document.getElementById("doc-preview");
const docSelector = document.getElementById("doc-selector");
const docUploadInput = document.getElementById("doc-upload");

chatForm.addEventListener("submit", handleChatSubmit);
saveDocButton.addEventListener("click", handleSaveEditorChanges);
continueStageButton.addEventListener("click", handleContinueStage);
chatInput.addEventListener("input", autoGrowComposer);
docPreviewInput.addEventListener("input", handleEditorInput);
docSelector.addEventListener("change", handleDocumentSelectionChange);
docUploadInput.addEventListener("change", handleUploadDocument);

updateDocumentPanel();
updateStagePlan();

async function handleChatSubmit(event) {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  if (!state.sessionId) {
    await createSession(message);
    return;
  }

  if (state.awaitingDocumentReview) {
    window.alert("先看一下右边文稿，再决定要不要继续下一阶段。");
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
        project_title: null,
      }),
    });
    if (!response.ok) throw new Error("创建会话失败");

    const data = await response.json();
    applySessionState(data);
    updateMeta(data.llm_status, data.current_round_label, data.remaining_rounds);
    updateQuestionChip(formatQuestions(data.current_questions));
    updateStagePlan(data.stage_plan);
    updateDocumentPanel();
    appendBubble("ai", buildQuestionsMessage(data.opening_message, data.current_questions));
  } catch (error) {
    appendBubble("ai", `Something went wrong while starting the session: ${error.message}`);
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
    if (!response.ok) throw new Error("提交这一轮内容失败");

    const data = await response.json();
    applyTurnState(data);
    updateMeta(null, data.current_round_label, data.remaining_rounds);
    updateStagePlan();
    updateDocumentPanel();
    appendBubble("ai", buildStageReplyMessage(data));

    if (data.is_complete) {
      updateQuestionChip("All stages are complete.");
      if (data.final_summary) {
        appendBubble("ai", `Here is the final wrap-up:\n${data.final_summary}`);
      }
      return;
    }

    if (data.awaiting_document_review) {
      updateQuestionChip("The draft on the right is ready. Click Confirm when you want the next stage.");
    } else {
      updateQuestionChip(formatQuestions(data.next_questions));
    }
  } catch (error) {
    appendBubble("ai", `This stage response could not be submitted: ${error.message}`);
  }
}

async function handleUploadDocument() {
  const selectedDoc = getSelectedDocument();
  if (!state.sessionId || !selectedDoc) return;
  if (!docUploadInput.files || !docUploadInput.files.length) return;

  const formData = new FormData();
  formData.append("file", docUploadInput.files[0]);

  try {
    const response = await fetch(
      `/dialogue/sessions/${state.sessionId}/documents/${selectedDoc.stage_index}/upload`,
      { method: "POST", body: formData },
    );
    if (!response.ok) throw new Error("上传修订文稿失败");

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
    window.alert("先把右边的修改保存一下，再继续。");
    return;
  }
  if (!isLatestDocumentSelected()) {
    window.alert("请先切回最新阶段的文稿，再继续。");
    return;
  }

  try {
    const response = await fetch(`/dialogue/sessions/${state.sessionId}/continue`, {
      method: "POST",
    });
    if (!response.ok) throw new Error("推进到下一阶段失败");

    const data = await response.json();
    state.awaitingDocumentReview = data.awaiting_document_review;
    state.activeStageNumber = data.active_stage_number;
    state.completedStageCount = data.completed_stage_count;
    state.currentQuestions = data.current_questions || [];
    syncDocumentState(data.current_document, data.stage_documents || []);

    updateMeta(null, data.current_round_label, data.remaining_rounds);
    updateStagePlan();
    updateDocumentPanel();
    updateQuestionChip(formatQuestions(data.current_questions));
    appendBubble("ai", buildQuestionsMessage(data.message, data.current_questions));
  } catch (error) {
    appendBubble("ai", `We cannot move to the next stage yet: ${error.message}`);
  }
}

async function handleSaveEditorChanges() {
  const selectedDoc = getSelectedDocument();
  if (!state.sessionId || !selectedDoc) return;

  const content = docPreviewInput.value.trim();
  if (!content) {
    window.alert("右边文稿不能是空的。");
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
    if (!response.ok) throw new Error("保存编辑内容失败");

    const data = await response.json();
    syncDocumentState(data.current_document, data.stage_documents || [], {
      preserveSelection: true,
      selectedStageIndex: selectedDoc.stage_index,
    });
    state.editorDirty = false;
    updateDocumentPanel();
    appendBubble("ai", data.message);
  } catch (error) {
    appendBubble("ai", `Saving the draft failed: ${error.message}`);
  }
}

function applySessionState(data) {
  state.sessionId = data.session_id;
  state.planConfirmed = data.plan_confirmed;
  state.fullStagePlan = Array.isArray(data.stage_plan) ? data.stage_plan : [];
  state.currentQuestions = data.current_questions || [];
  state.awaitingDocumentReview = data.awaiting_document_review;
  state.activeStageNumber = data.active_stage_number;
  state.completedStageCount = data.completed_stage_count || 0;
  state.isComplete = data.is_complete;
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
  const llmStatusEl = document.getElementById("llm-status");
  const roundLabelEl = document.getElementById("round-label");
  const roundsLeftEl = document.getElementById("rounds-left");

  if (llmStatusEl && llmStatus !== null && llmStatus !== undefined) {
    llmStatusEl.textContent = llmStatus;
  }
  if (roundLabelEl) {
    roundLabelEl.textContent = roundLabel;
  }
  if (roundsLeftEl) {
    roundsLeftEl.textContent = String(remainingRounds);
  }
}

function updateStagePlan(stagePlan = null) {
  if (Array.isArray(stagePlan)) {
    state.fullStagePlan = stagePlan;
  }

  const stageList = document.getElementById("stage-plan");
  const visibleStages = getVisibleStagePlan();

  if (!visibleStages.length) {
    stageList.innerHTML = `
      <li class="stage-item pending">
        <div class="stage-index">1</div>
        <div class="stage-content">
          <p class="stage-label">等待开始</p>
          <p class="stage-reason">先抛出你的大致想法，Stage 1 会出现在这里。</p>
        </div>
      </li>
    `;
  } else {
    stageList.innerHTML = visibleStages
      .map(
        (stage) => `
          <li class="stage-item pending" data-index="${stage.index}">
            <div class="stage-index">${stage.index}</div>
            <div class="stage-content">
              <p class="stage-label">${stage.label}</p>
              <p class="stage-reason">${stage.reason}</p>
            </div>
          </li>
        `,
      )
      .join("");
  }

  const items = Array.from(stageList.querySelectorAll(".stage-item[data-index]"));
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

  const total = state.fullStagePlan.length;
  const revealed = visibleStages.length;
  const summary = document.getElementById("stage-summary");
  if (!total) {
    summary.textContent = "准备开始";
  } else if (state.isComplete) {
    summary.textContent = "已完成";
  } else if (state.awaitingDocumentReview) {
    summary.textContent = `Stage ${state.completedStageCount} 已完成`;
  } else if (state.activeStageNumber) {
    summary.textContent = `Stage ${state.activeStageNumber} / ${Math.max(revealed, 1)}`;
  } else {
    summary.textContent = `已展开 ${revealed} 个阶段`;
  }
}

function getVisibleStagePlan() {
  if (!state.fullStagePlan.length) {
    return [];
  }

  const total = state.fullStagePlan.length;
  let visibleCount = 1;

  if (state.isComplete) {
    visibleCount = total;
  } else if (state.awaitingDocumentReview) {
    visibleCount = Math.max(state.completedStageCount, 1);
  } else if (state.activeStageNumber) {
    visibleCount = Math.max(state.activeStageNumber, 1);
  }

  return state.fullStagePlan.slice(0, Math.min(visibleCount, total));
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
      ? "历史版本"
      : doc.is_modified
        ? "已修改"
        : doc.source === "uploaded"
          ? "已上传"
          : "已生成"
    : "未就绪";

  docPreviewInput.value = doc?.preview_text || "右侧会显示当前阶段文稿。";
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
  const hasPreferredSelection = preferredStageIndex !== null
    && state.stageDocuments.some((doc) => doc.stage_index === preferredStageIndex);
  const hasCurrentSelection = options.preserveSelection
    && state.selectedDocumentStageIndex !== null
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
    docSelector.innerHTML = `<option value="">暂无文稿</option>`;
    docSelector.disabled = true;
    return;
  }

  docSelector.disabled = false;
  docSelector.innerHTML = state.stageDocuments
    .map((doc) => {
      const suffix = doc.is_modified ? "（已修改）" : "";
      const selected = doc.stage_index === state.selectedDocumentStageIndex ? " selected" : "";
      return (
        `<option value="${doc.stage_index}"${selected}>` +
        `Stage ${doc.stage_index} - ${doc.stage_label}${suffix}` +
        "</option>"
      );
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
    const shouldSwitch = window.confirm("右边还有没保存的修改，确定直接切换吗？");
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
  if (!doc) return "只读";
  if (state.editorDirty) return "有未保存修改";
  if (!latestSelected) return "正在查看历史阶段";
  return "可编辑";
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
  if (!questions || !questions.length) return "No more questions right now.";
  const lines = questions.map((question, index) => `${index + 1}. ${question}`);
  return lines.join(withLineBreak ? "\n" : " | ");
}

function buildQuestionsMessage(message, questions) {
  const sections = [];
  if (message) {
    sections.push(message);
  }
  if (questions && questions.length) {
    const stageLabel = state.activeStageNumber
      ? `Stage ${state.activeStageNumber} questions`
      : "A couple of quick questions";
    sections.push(`${stageLabel}:\n${formatQuestions(questions, true)}`);
  }
  return sections.filter(Boolean).join("\n\n");
}

function buildStageReplyMessage(data) {
  const sections = [];
  if (data.stage_feedback) {
    sections.push(data.stage_feedback);
  }
  if (data.guidance) {
    sections.push(data.guidance);
  }
  if (data.is_complete) {
    sections.push("The final draft is on the right now.");
  } else if (data.awaiting_document_review) {
    sections.push("I put this stage draft on the right. Review it first, then click Confirm if you want the next stage.");
  } else if (data.message) {
    sections.push(data.message);
  }
  return sections.filter(Boolean).join("\n\n");
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
  document.getElementById("doc-editor-status").textContent = "有未保存修改";
}

function removeEmptyState() {
  const emptyState = chatFeed.querySelector(".empty-state");
  if (emptyState) emptyState.remove();
}
