const apiKeyInput = document.querySelector("#api-key");
const chatLog = document.querySelector("#chat-log");
const chatForm = document.querySelector("#chat-form");
const userInput = document.querySelector("#user-input");
const sendButton = document.querySelector("#send-button");

const conversation = [];

const systemPrompt = `
당신은 한국어로 답하는 영화 전문가 챗봇입니다.
영화 추천, 감독/배우/장르/시대적 맥락, 촬영/편집/음악/서사 분석을 전문적으로 다룹니다.
사용자의 취향과 이전 대화를 반영해 멀티턴으로 이어가세요.
모르는 최신 정보는 확정적으로 꾸미지 말고, 확인이 필요하다고 말하세요.
답변은 친절하고 구체적으로 하되, 스포일러가 중요한 경우 먼저 경고하세요.
`.trim();

function addMessage(role, text, variant = role) {
  const article = document.createElement("article");
  article.className = `message ${variant}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  article.appendChild(bubble);
  chatLog.appendChild(article);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function setLoading(isLoading) {
  sendButton.disabled = isLoading;
  sendButton.textContent = isLoading ? "응답 중" : "전송";
}

function buildInput() {
  return conversation.map((message) => ({
    role: message.role,
    content: message.content,
  }));
}

function extractResponseText(data) {
  if (typeof data.output_text === "string" && data.output_text.trim()) {
    return data.output_text.trim();
  }

  const textParts = [];
  for (const item of data.output ?? []) {
    for (const content of item.content ?? []) {
      if (content.type === "output_text" && content.text) {
        textParts.push(content.text);
      }
    }
  }

  return textParts.join("\n").trim();
}

async function askMovieExpert(apiKey) {
  const response = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: "gpt-4.1-mini",
      instructions: systemPrompt,
      input: buildInput(),
      temperature: 0.8,
    }),
  });

  const data = await response.json();

  if (!response.ok) {
    const message =
      data.error?.message ?? "요청을 처리하지 못했습니다. API 키와 결제 상태를 확인해 주세요.";
    throw new Error(message);
  }

  return extractResponseText(data) || "응답을 읽지 못했습니다. 다시 질문해 주세요.";
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const apiKey = apiKeyInput.value.trim();
  const question = userInput.value.trim();

  if (!apiKey) {
    addMessage("assistant", "먼저 최상단에 OpenAI API 키를 입력해 주세요.", "error");
    apiKeyInput.focus();
    return;
  }

  if (!question) {
    userInput.focus();
    return;
  }

  conversation.push({ role: "user", content: question });
  addMessage("user", question);
  userInput.value = "";
  setLoading(true);

  try {
    const answer = await askMovieExpert(apiKey);
    conversation.push({ role: "assistant", content: answer });
    addMessage("assistant", answer);
  } catch (error) {
    conversation.pop();
    addMessage("assistant", error.message, "error");
  } finally {
    setLoading(false);
    userInput.focus();
  }
});

userInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});
