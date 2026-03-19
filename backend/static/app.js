const state = {
  sessionId: null,
  planConfirmed: false,
  awaitingStageConfirmation: false,
  currentQuestions: [],
};

const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const projectTitleInput = document.getElementById("project-title");
const chatFeed = document.getElementById("chat-feed");
const confirmPlanButton = document.getElementById("confirm-plan");
const toggleAdjustButton = document.getElementById("toggle-adjust");
const submitAdjustmentButton = document.getElementById("submit-adjustment");

chatForm.addEventListener("submit", handleChatSubmit);
confirmPlanButton.addEventListener("click", handleConfirmPlan);
toggleAdjustButton.addEventListener("click", toggleAdjustmentBox);
submitAdjustmentButton.addEventListener("click", handleAdjustPlan);
chatInput.addEventListener("input", autoGrowComposer);

async function handleChatSubmit(event) {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  if (!state.sessionId) {
    await createSession(message);
    return;
  }

  if (!state.planConfirmed) {
    window.alert("请先在左侧确认阶段安排，或者填写调整意见。");
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
    if (!response.ok) {
      throw new Error("创建会话失败");
    }

    const data = await response.json();
    state.sessionId = data.session_id;
    state.planConfirmed = data.plan_confirmed;
    state.awaitingStageConfirmation = true;
    state.currentQuestions = data.current_questions;

    updateMeta(data.llm_status, data.current_round_label, data.remaining_rounds);
    updateStagePlan(data.stage_plan, data.current_round_label, false);
    updateQuestionChip("请先查看左侧阶段安排，并决定是否确认。");
    showPlanPanel(true);
    appendBubble("ai", data.opening_message);
  } catch (error) {
    appendBubble("ai", `我这边创建会话时出了点问题：${error.message}`);
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
    if (!response.ok) {
      throw new Error("确认阶段方案失败");
    }

    const data = await response.json();
    state.planConfirmed = data.plan_confirmed;
    state.awaitingStageConfirmation = false;
    state.currentQuestions = data.current_questions;

    updateStagePlan(data.stage_plan, data.current_round_label, false);
    updateMeta(
      document.getElementById("llm-status").textContent,
      data.current_round_label,
      data.remaining_rounds,
    );
    updateQuestionChip(formatQuestions(data.current_questions));
    appendBubble("ai", `${data.message}\n\n本轮问题：\n${formatQuestions(data.current_questions, true)}`);
    showPlanPanel(false);
  } catch (error) {
    appendBubble("ai", `阶段确认失败：${error.message}`);
  }
}

async function handleAdjustPlan() {
  if (!state.sessionId) return;

  const adjustmentText = document.getElementById("adjustment-text").value.trim();
  if (!adjustmentText) {
    window.alert("请先输入你想调整的阶段安排。");
    return;
  }

  appendBubble("user", `我想调整阶段安排：\n${adjustmentText}`);

  try {
    const response = await fetch(`/dialogue/sessions/${state.sessionId}/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        confirmed: false,
        adjustment_text: adjustmentText,
      }),
    });
    if (!response.ok) {
      throw new Error("调整阶段方案失败");
    }

    const data = await response.json();
    state.planConfirmed = data.plan_confirmed;
    state.awaitingStageConfirmation = false;
    state.currentQuestions = data.current_questions;

    updateStagePlan(data.stage_plan, data.current_round_label, false);
    updateMeta(
      document.getElementById("llm-status").textContent,
      data.current_round_label,
      data.remaining_rounds,
    );
    updateQuestionChip(formatQuestions(data.current_questions));
    appendBubble("ai", `${data.message}\n\n本轮问题：\n${formatQuestions(data.current_questions, true)}`);
    document.getElementById("adjustment-text").value = "";
    document.getElementById("adjustment-box").classList.add("hidden");
    showPlanPanel(false);
  } catch (error) {
    appendBubble("ai", `调整阶段方案失败：${error.message}`);
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
    if (!response.ok) {
      throw new Error("提交这一轮失败");
    }

    const data = await response.json();

    const aiMessage = [
      data.message,
      "",
      "一点反馈：",
      data.stage_feedback,
      "",
      "建议思路：",
      data.guidance,
      "",
      "阶段草稿：",
      data.draft,
    ].join("\n");

    appendBubble("ai", aiMessage);

    if (data.is_complete) {
      updateQuestionChip("本轮对话已经完成");
      updateMeta(document.getElementById("llm-status").textContent, "已完成所有轮次", 0);
      updateStagePlan([], "已完成所有轮次", true);
      appendBubble("ai", `最终总结：\n${data.final_summary || ""}`);
      return;
    }

    state.currentQuestions = data.next_questions;
    updateMeta(
      document.getElementById("llm-status").textContent,
      data.current_round_label,
      data.remaining_rounds,
    );
    updateQuestionChip(formatQuestions(data.next_questions));
    updateStagePlan(null, data.current_round_label, false);
  } catch (error) {
    appendBubble("ai", `这一轮提交失败：${error.message}`);
  }
}

function updateMeta(llmStatus, roundLabel, remainingRounds) {
  document.getElementById("llm-status").textContent = llmStatus;
  document.getElementById("round-label").textContent = roundLabel;
  document.getElementById("rounds-left").textContent = String(remainingRounds);
}

function updateStagePlan(stagePlan, roundLabel, forceComplete) {
  const stageList = document.getElementById("stage-plan");
  const currentIndex = parseRoundIndex(roundLabel);

  if (Array.isArray(stagePlan) && stagePlan.length) {
    stageList.innerHTML = "";
    stagePlan.forEach((stage) => {
      const item = document.createElement("li");
      item.className = "stage-item pending";
      item.dataset.index = String(stage.index);

      const index = document.createElement("div");
      index.className = "stage-index";
      index.textContent = stage.index;

      const content = document.createElement("div");
      content.className = "stage-content";

      const label = document.createElement("p");
      label.className = "stage-label";
      label.textContent = stage.label;

      const reason = document.createElement("p");
      reason.className = "stage-reason";
      reason.textContent = stage.reason;

      content.appendChild(label);
      content.appendChild(reason);
      item.appendChild(index);
      item.appendChild(content);
      stageList.appendChild(item);
    });
  }

  const items = Array.from(stageList.querySelectorAll(".stage-item"));
  items.forEach((item) => {
    const index = Number(item.dataset.index || 0);
    item.classList.remove("active", "completed", "pending");

    if (forceComplete) {
      item.classList.add("completed");
      return;
    }

    if (!currentIndex) {
      item.classList.add("pending");
      return;
    }

    if (index < currentIndex) {
      item.classList.add("completed");
    } else if (index === currentIndex) {
      item.classList.add("active");
    } else {
      item.classList.add("pending");
    }
  });

  const total = items.length;
  if (!total) {
    document.getElementById("stage-summary").textContent = "等待阶段规划";
    return;
  }
  if (forceComplete) {
    document.getElementById("stage-summary").textContent = "全部完成";
    return;
  }
  if (currentIndex) {
    document.getElementById("stage-summary").textContent = `当前第 ${currentIndex}/${total} 阶段`;
  } else {
    document.getElementById("stage-summary").textContent = `共 ${total} 个阶段`;
  }
}

function updateQuestionChip(text) {
  document.getElementById("question-chip").textContent = text;
}

function appendBubble(role, content) {
  removeEmptyState();
  const template = document.getElementById("bubble-template");
  const node = template.content.firstElementChild.cloneNode(true);
  node.classList.add(role === "user" ? "user" : "ai");
  node.querySelector(".avatar").textContent = "";
  node.querySelector(".bubble").textContent = content;
  chatFeed.appendChild(node);
  chatFeed.scrollTop = chatFeed.scrollHeight;
}

function parseUserReply(rawMessage) {
  const blocks = rawMessage
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean);

  if (blocks.length === 0) {
    return { answers: [rawMessage], latestInput: null };
  }

  if (blocks.length === 1) {
    return { answers: [blocks[0]], latestInput: null };
  }

  if (blocks.length === 2) {
    return { answers: [blocks[0], blocks[1]], latestInput: null };
  }

  return {
    answers: [blocks[0], blocks[1]],
    latestInput: blocks.slice(2).join("\n\n"),
  };
}

function parseRoundIndex(roundLabel) {
  const match = /第\s*(\d+)\s*\/\s*(\d+)/.exec(roundLabel || "");
  if (!match) return null;
  return Number(match[1]);
}

function formatQuestions(questions, withLineBreak = false) {
  if (!questions || !questions.length) {
    return "当前没有待回答问题。";
  }
  const lines = questions.map((question, index) => `${index + 1}. ${question}`);
  return lines.join(withLineBreak ? "\n" : "  |  ");
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

function removeEmptyState() {
  const emptyState = chatFeed.querySelector(".empty-state");
  if (emptyState) {
    emptyState.remove();
  }
}
