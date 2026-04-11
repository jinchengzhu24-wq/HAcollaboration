const state = {
  sessionId: null,
  projectTitle: "Research document",
  openingMessage: "",
  stages: [],
  activeStageIndex: null,
  currentQuestions: [],
  currentRoundLabel: "",
  isComplete: false,
  documentDrafts: {},
  nextStepDrafts: {},
};

const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatFeed = document.getElementById("chat-feed");
const stagePlanEl = document.getElementById("stage-plan");
const questionChipEl = document.getElementById("question-chip");
const stageSummaryEl = document.getElementById("stage-summary");
const activeStageLabelEl = document.getElementById("active-stage-label");
const confirmStageButton = document.getElementById("confirm-stage-button");
const regenerateStageButton = document.getElementById("regenerate-stage-button");
const documentTitleEl = document.getElementById("document-title");
const combinedDocumentEl = document.getElementById("combined-document");
const saveDocumentButton = document.getElementById("save-document-button");

chatForm.addEventListener("submit", handleChatSubmit);
chatInput.addEventListener("input", autoGrowComposer);
stagePlanEl.addEventListener("click", handleStageListClick);
combinedDocumentEl.addEventListener("input", handleDocumentInput);
confirmStageButton.addEventListener("click", handleConfirmCurrentStage);
regenerateStageButton.addEventListener("click", handleRegenerateCurrentStage);
saveDocumentButton.addEventListener("click", saveCombinedDocument);

renderStagePlan();
renderDocument();
renderMeta();

async function handleChatSubmit(event) {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  appendBubble("user", message);
  clearComposer();

  if (!state.sessionId) {
    await createSession(message);
    return;
  }

  const command = parseStageCommand(message);
  if (command?.type === "delete") {
    await deleteStage(command.stageIndex);
    return;
  }
  if (command?.type === "jump") {
    await activateStage(command.stageIndex);
    return;
  }

  const activeStage = getActiveStage();
  if (!activeStage) {
    appendBubble("ai", "There is no active stage right now.");
    return;
  }

  const parsed = parseUserReply(message);
  await stageRequest(
    `/dialogue/sessions/${state.sessionId}/stages/${activeStage.index}/turn`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        answers: parsed.answers,
        latest_input: parsed.latestInput,
      }),
    },
    { includeQuestions: true },
  );
}

async function createSession(initialIdea) {
  try {
    const response = await fetch("/dialogue/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        initial_idea: initialIdea,
        project_title: null,
      }),
    });
    if (!response.ok) throw new Error("Could not create a session.");
    const data = await response.json();
    applySessionState(data);
    removeEmptyState();
    appendBubble("ai", buildAssistantMessage(data, true));
  } catch (error) {
    appendBubble("ai", `Failed to start the session: ${error.message}`);
  }
}

async function handleConfirmCurrentStage() {
  const activeStage = getActiveStage();
  if (!activeStage) return;
  await stageRequest(`/dialogue/sessions/${state.sessionId}/stages/${activeStage.index}/confirm`, {
    method: "POST",
  }, { includeQuestions: true });
}

async function handleRegenerateCurrentStage() {
  const activeStage = getActiveStage();
  if (!activeStage) return;
  await stageRequest(`/dialogue/sessions/${state.sessionId}/stages/${activeStage.index}/regenerate`, {
    method: "POST",
  }, { includeQuestions: true });
}

async function saveCombinedDocument() {
  if (!state.sessionId) return;
  const content = buildCombinedDocumentPayload();
  try {
    const response = await fetch(`/dialogue/sessions/${state.sessionId}/document/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!response.ok) {
      const payload = await safeJson(response);
      throw new Error(payload?.detail || "Could not save the document.");
    }
    const data = await response.json();
    applySessionState(data);
    appendBubble("ai", buildAssistantMessage(data));
  } catch (error) {
    appendBubble("ai", `Document save failed: ${error.message}`);
  }
}

async function deleteStage(stageIndex) {
  await stageRequest(`/dialogue/sessions/${state.sessionId}/stages/${stageIndex}/delete`, {
    method: "POST",
  }, { includeQuestions: true });
}

async function activateStage(stageIndex) {
  await stageRequest(`/dialogue/sessions/${state.sessionId}/stages/${stageIndex}/activate`, {
    method: "POST",
  }, { includeQuestions: true });
}

async function stageRequest(url, options, extra = {}) {
  try {
    const response = await fetch(url, options);
    if (!response.ok) {
      const payload = await safeJson(response);
      throw new Error(payload?.detail || "Request failed.");
    }
    const data = await response.json();
    applySessionState(data);
    appendBubble("ai", buildAssistantMessage(data, extra.includeQuestions === true));
  } catch (error) {
    appendBubble("ai", `Action failed: ${error.message}`);
  }
}

function applySessionState(data) {
  state.sessionId = data.session_id;
  state.projectTitle = data.project_title || "Research document";
  state.openingMessage = data.opening_message || "";
  state.stages = Array.isArray(data.stages) ? data.stages : [];
  state.activeStageIndex = data.active_stage_index;
  state.currentQuestions = Array.isArray(data.current_questions) ? data.current_questions : [];
  state.currentRoundLabel = data.current_round_label || "";
  state.isComplete = Boolean(data.is_complete);

  const drafts = {};
  const nextSteps = {};
  state.stages.forEach((stage) => {
    drafts[stage.index] = (stage.draft || extractStageBody(stage) || "").trim();
    nextSteps[stage.index] = String(stage.guidance || "").trim();
  });
  state.documentDrafts = drafts;
  state.nextStepDrafts = nextSteps;

  renderStagePlan();
  renderDocument();
  renderMeta();
}

function renderMeta() {
  documentTitleEl.textContent = state.projectTitle || "Research document";
  stageSummaryEl.textContent = state.currentRoundLabel || "Start a session to load the stage map.";
  activeStageLabelEl.textContent = state.activeStageIndex
    ? `Active: Stage ${state.activeStageIndex}`
    : "No active stage";
  questionChipEl.textContent = formatQuestions(state.currentQuestions);

  const activeStage = getActiveStage();
  confirmStageButton.disabled = !activeStage || !activeStage.can_confirm;
  regenerateStageButton.disabled = !activeStage || !activeStage.can_regenerate;
  saveDocumentButton.disabled = !state.sessionId;
}

function renderStagePlan() {
  if (!state.stages.length) {
    stagePlanEl.innerHTML = `
      <li class="stage-item is-empty">
        <div class="stage-index">1</div>
        <div class="stage-main">
          <p class="stage-label">Waiting to start</p>
          <p class="stage-reason">A new session will generate the four CAR stages immediately.</p>
        </div>
      </li>
    `;
    return;
  }

  stagePlanEl.innerHTML = state.stages
    .map((stage) => {
      const classes = [
        "stage-item",
        stage.is_active ? "is-active" : "",
        stage.status === "locked" ? "is-locked" : "",
        stage.status === "deleted" ? "is-deleted" : "",
        stage.is_outdated ? "is-outdated" : "",
      ]
        .filter(Boolean)
        .join(" ");

      return `
        <li class="${classes}" data-stage-index="${stage.index}">
          <div class="stage-index">${stage.index}</div>
          <div class="stage-main">
            <div class="stage-topline">
              <p class="stage-label">${escapeHtml(stage.label)}</p>
              <div class="stage-badges">${buildStageBadges(stage)}</div>
            </div>
            <p class="stage-reason">${escapeHtml(stage.reason)}</p>
          </div>
        </li>
      `;
    })
    .join("");
}

function renderDocument() {
  const visibleStages = state.stages.filter((stage) => stage.status !== "deleted");
  if (!visibleStages.length) {
    combinedDocumentEl.innerHTML = `<p class="doc-empty">The document will appear here after you start a session.</p>`;
    return;
  }

  combinedDocumentEl.innerHTML = visibleStages
    .map((stage) => {
      const body = state.documentDrafts[stage.index] || "";
      const editable = stage.status !== "locked";
      const placeholder = editable
        ? "Write or revise this stage here."
        : "This stage will become editable after earlier stages are confirmed or skipped.";
      return `
        <section class="doc-section ${editable ? "" : "is-locked"}">
          <h3>Stage ${stage.index}: ${escapeHtml(stage.label)}</h3>
          <div class="doc-edit-grid">
            <div class="doc-edit-card">
              <p class="doc-edit-label">Working Draft</p>
              <div
                class="doc-body ${editable ? "" : "is-readonly"}"
                data-stage-index="${stage.index}"
                data-field="draft"
                data-placeholder="${escapeHtml(placeholder)}"
                contenteditable="${editable ? "true" : "false"}"
                spellcheck="false"
              >${formatEditableText(body)}</div>
            </div>
            <div class="doc-edit-card">
              <p class="doc-edit-label">Next Step</p>
              <div
                class="doc-body doc-body-compact ${editable ? "" : "is-readonly"}"
                data-stage-index="${stage.index}"
                data-field="guidance"
                data-placeholder="Describe the next move for this stage."
                contenteditable="${editable ? "true" : "false"}"
                spellcheck="false"
              >${formatEditableText(state.nextStepDrafts[stage.index] || "")}</div>
            </div>
          </div>
          ${renderStageSupport(stage)}
        </section>
      `;
    })
    .join("");
}

function handleStageListClick(event) {
  const item = event.target.closest("[data-stage-index]");
  if (!item) return;
  const stageIndex = Number(item.dataset.stageIndex);
  const stage = getStage(stageIndex);
  if (!stage || !stage.can_activate) return;
  activateStage(stageIndex);
}

function handleDocumentInput(event) {
  const body = event.target.closest(".doc-body[data-stage-index]");
  if (!body) return;
  const stageIndex = Number(body.dataset.stageIndex);
  const field = body.dataset.field;
  const text = normalizeEditableText(body.innerText);
  if (field === "guidance") {
    state.nextStepDrafts[stageIndex] = text;
    return;
  }
  state.documentDrafts[stageIndex] = text;
}

function buildCombinedDocumentPayload() {
  return state.stages
    .filter((stage) => stage.status !== "deleted")
    .map((stage) => {
      const body = (state.documentDrafts[stage.index] || "").trim();
      const nextStep = (state.nextStepDrafts[stage.index] || "").trim();
      const lines = [
        `Stage ${stage.index}: ${stage.label}`,
        "Working Draft:",
        body || "This stage still needs more detail.",
      ];
      if (nextStep) {
        lines.push("", "Next Step:", nextStep);
      }
      return lines.join("\n");
    })
    .join("\n\n");
}

function buildAssistantMessage(data, includeQuestions = false) {
  const sections = [];
  if (data.message) sections.push(data.message);
  if (!data.message && state.openingMessage) sections.push(state.openingMessage);
  if (includeQuestions && state.currentQuestions.length) {
    sections.push(`Current stage questions:\n${formatQuestions(state.currentQuestions, true)}`);
  }
  if (data.is_complete) {
    sections.push("All remaining stages are now completed or skipped.");
  }
  return sections.filter(Boolean).join("\n\n");
}

function renderStageSupport(stage) {
  const blocks = [];

  if (stage.feedback) {
    blocks.push(`
      <div class="doc-support-block">
        <p class="doc-support-title">System Feedback</p>
        <p class="doc-support-copy">${escapeHtml(stage.feedback)}</p>
      </div>
    `);
  }

  if (stage.guidance) {
    blocks.push(`
      <div class="doc-support-block">
        <p class="doc-support-title">Next Step</p>
        <p class="doc-support-copy">${escapeHtml(stage.guidance)}</p>
      </div>
    `);
  }

  if (Array.isArray(stage.questions) && stage.questions.length) {
    blocks.push(`
      <div class="doc-support-block">
        <p class="doc-support-title">If You Continue This Stage</p>
        <ol class="doc-question-list">
          ${stage.questions.map((question) => `<li>${escapeHtml(question)}</li>`).join("")}
        </ol>
      </div>
    `);
  }

  return blocks.join("");
}

function buildStageBadges(stage) {
  const badges = [
    `<span class="stage-badge stage-badge-main">${escapeHtml(primaryStageBadge(stage))}</span>`,
  ];
  if (stage.is_outdated) {
    badges.push('<span class="stage-badge stage-badge-warn">Outdated</span>');
  }
  return badges.join("");
}

function primaryStageBadge(stage) {
  if (stage.status === "deleted") return "Deleted";
  if (stage.is_active) return "Active";
  if (stage.needs_confirmation) return "Needs confirm";
  if (stage.status === "completed") return "Completed";
  if (stage.status === "skipped") return "Skipped";
  if (stage.status === "locked") return "Locked";
  return "Available";
}

function extractStageBody(stage) {
  const preview = stage.document?.preview_text || "";
  const lines = preview.split(/\r?\n/).map((line) => line.trim());
  let startIndex = 0;
  if (lines[0] && lines[0] !== `Stage ${stage.index}: ${stage.label}`) {
    startIndex = 1;
  }
  if (lines[startIndex] === `Stage ${stage.index}: ${stage.label}`) {
    startIndex += 1;
  }
  const normalized = lines.slice(startIndex).join("\n").trim();
  return normalized || "";
}

function parseUserReply(rawMessage) {
  const blocks = rawMessage
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (blocks.length <= 1) return { answers: [rawMessage.trim()], latestInput: null };
  if (blocks.length === 2) return { answers: blocks, latestInput: null };
  return {
    answers: blocks.slice(0, 2),
    latestInput: blocks.slice(2).join("\n\n"),
  };
}

function parseStageCommand(message) {
  const deleteMatch = message.match(/^delete\s+stage\s*(\d+)$/i);
  if (deleteMatch) {
    return { type: "delete", stageIndex: Number(deleteMatch[1]) };
  }

  const jumpMatch = message.match(/^jump\s+into\s+stage\s*(\d+)$/i);
  if (jumpMatch) {
    return { type: "jump", stageIndex: Number(jumpMatch[1]) };
  }

  return null;
}

function formatQuestions(questions, withLineBreak = false) {
  if (!questions || !questions.length) return "No extra prompts for the current stage.";
  const lines = questions.map((question, index) => `${index + 1}. ${question}`);
  return lines.join(withLineBreak ? "\n" : " | ");
}

function formatEditableText(text) {
  if (!text) return "";
  return escapeHtml(text).replace(/\n/g, "<br>");
}

function normalizeEditableText(text) {
  return String(text || "")
    .replace(/\u00a0/g, " ")
    .replace(/\r/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function getActiveStage() {
  return state.stages.find((stage) => stage.index === state.activeStageIndex) || null;
}

function getStage(stageIndex) {
  return state.stages.find((stage) => stage.index === stageIndex) || null;
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

function removeEmptyState() {
  const emptyState = chatFeed.querySelector(".empty-state");
  if (emptyState) emptyState.remove();
}

function autoGrowComposer() {
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 180)}px`;
}

function clearComposer() {
  chatInput.value = "";
  chatInput.style.height = "auto";
}

function safeJson(response) {
  return response.json().catch(() => null);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
