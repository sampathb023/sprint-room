const startView = document.querySelector("#startView");
const joinView = document.querySelector("#joinView");
const roomView = document.querySelector("#roomView");
const retroView = document.querySelector("#retroView");
const sessionNotice = document.querySelector("#sessionNotice");
const createSessionButton = document.querySelector("#createSessionButton");
const createRetroButton = document.querySelector("#createRetroButton");
const joinForm = document.querySelector("#joinForm");
const nameInput = document.querySelector("#nameInput");
const storyTitle = document.querySelector("#storyTitle");
const storyDescription = document.querySelector("#storyDescription");
const storyList = document.querySelector("#storyList");
const storyCount = document.querySelector("#storyCount");
const storyForm = document.querySelector("#storyForm");
const newStoryTitle = document.querySelector("#newStoryTitle");
const newStoryDescription = document.querySelector("#newStoryDescription");
const pointButtons = document.querySelector("#pointButtons");
const participants = document.querySelector("#participants");
const revealButton = document.querySelector("#revealButton");
const resetButton = document.querySelector("#resetButton");
const nextStoryButton = document.querySelector("#nextStoryButton");
const copyLinkButton = document.querySelector("#copyLinkButton");
const newSessionButton = document.querySelector("#newSessionButton");
const copyRetroLinkButton = document.querySelector("#copyRetroLinkButton");
const newRetroSessionButton = document.querySelector("#newRetroSessionButton");
const revealRetroButton = document.querySelector("#revealRetroButton");
const retroPrivacyNotice = document.querySelector("#retroPrivacyNotice");
const averageValue = document.querySelector("#averageValue");
const voteDistribution = document.querySelector("#voteDistribution");
const voteCount = document.querySelector("#voteCount");
const connectionStatus = document.querySelector("#connectionStatus");
const toast = document.querySelector("#toast");
const retroColumns = {
  wentWell: document.querySelector("#wentWellItems"),
  improve: document.querySelector("#improveItems"),
  feedback: document.querySelector("#feedbackItems"),
};

let socket;
let sessionId = new URLSearchParams(location.search).get("session");
let participantId = localStorage.getItem("sprint-room-participant");
let participantName = localStorage.getItem("sprint-room-name") || "";
let selectedVote = null;
let titleTimer;
let descriptionTimer;
let shouldReconnect = true;
let canManage = false;
let sessionMode = "pointing";

if (!participantId) {
  participantId = crypto.randomUUID();
  localStorage.setItem("sprint-room-participant", participantId);
}

nameInput.value = participantName;

initialize();

async function initialize() {
  if (!sessionId) {
    return;
  }
  const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`);
  if (response.ok) {
    const data = await response.json();
    sessionMode = data.mode || "pointing";
    startView.classList.add("hidden");
    joinView.classList.remove("hidden");
    return;
  }
  sessionId = null;
  history.replaceState(null, "", "/");
  sessionNotice.classList.remove("hidden");
  startView.classList.remove("hidden");
  joinView.classList.add("hidden");
  roomView.classList.add("hidden");
}

async function createSession(mode = "pointing") {
  const response = await fetch("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
  const data = await response.json();
  sessionId = data.id;
  sessionMode = data.mode || mode;
  saveFacilitatorKey(sessionId, data.facilitatorKey);
  history.replaceState(null, "", `/?session=${sessionId}`);
}

function getFacilitatorKeys() {
  try {
    return JSON.parse(localStorage.getItem("sprint-room-facilitators") || "{}");
  } catch {
    return {};
  }
}

function getFacilitatorKey() {
  return getFacilitatorKeys()[sessionId] || "";
}

function saveFacilitatorKey(id, key) {
  const keys = getFacilitatorKeys();
  keys[id] = key;
  localStorage.setItem("sprint-room-facilitators", JSON.stringify(keys));
}

function shareUrl() {
  const url = new URL(location.href);
  url.search = `?session=${encodeURIComponent(sessionId)}`;
  return url.toString();
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 1800);
}

function send(message) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message));
  }
}

function connect() {
  shouldReconnect = true;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams({ session: sessionId });
  const facilitatorKey = getFacilitatorKey();
  if (facilitatorKey) {
    params.set("facilitatorKey", facilitatorKey);
  }
  socket = new WebSocket(`${scheme}://${location.host}/ws?${params.toString()}`);
  const currentSocket = socket;
  connectionStatus.textContent = "Connecting";

  socket.addEventListener("open", () => {
    connectionStatus.textContent = canManage ? "Live · facilitator" : "Live";
    send({ type: "join", name: participantName, participantId });
  });

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") {
      render(message.session);
    }
    if (message.type === "error") {
      sessionId = null;
      shouldReconnect = false;
      history.replaceState(null, "", "/");
      sessionNotice.classList.remove("hidden");
      startView.classList.remove("hidden");
      joinView.classList.add("hidden");
      roomView.classList.add("hidden");
      retroView.classList.add("hidden");
    }
  });

  socket.addEventListener("close", () => {
    if (!shouldReconnect || currentSocket !== socket) {
      return;
    }
    connectionStatus.textContent = "Reconnecting";
    window.setTimeout(connect, 900);
  });
}

function render(session) {
  sessionMode = session.mode || "pointing";
  if (sessionMode === "retro") {
    renderRetro(session);
    return;
  }
  roomView.classList.remove("hidden");
  retroView.classList.add("hidden");
  canManage = session.canManage;
  connectionStatus.textContent = canManage ? "Live · facilitator" : "Live";
  if (document.activeElement !== storyTitle) {
    storyTitle.value = session.title;
  }
  if (document.activeElement !== storyDescription) {
    storyDescription.value = session.description;
  }
  storyTitle.disabled = !canManage;
  storyDescription.disabled = !canManage;
  storyForm.classList.toggle("hidden", !canManage);
  revealButton.disabled = !canManage;
  resetButton.disabled = !canManage;
  nextStoryButton.disabled = !canManage;
  const currentParticipant = session.participants.find((person) => person.id === participantId);
  if (currentParticipant) {
    selectedVote = currentParticipant.vote;
  }
  pointButtons.replaceChildren(
    ...session.points.map((point) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `point${selectedVote === point ? " selected" : ""}`;
      button.textContent = point;
      button.addEventListener("click", () => {
        selectedVote = point;
        send({ type: "vote", value: point });
        [...pointButtons.children].forEach((child) => child.classList.toggle("selected", child.textContent === point));
      });
      return button;
    }),
  );

  const voted = session.participants.filter((person) => person.hasVoted).length;
  voteCount.textContent = `${voted} of ${session.participants.length} voted`;
  averageValue.textContent = session.average ?? (session.revealed ? "No votes" : "Hidden");
  voteDistribution.replaceChildren(
    ...(session.distribution.length
      ? session.distribution.map((item) => {
          const row = document.createElement("div");
          row.className = "distribution-row";

          const point = document.createElement("strong");
          point.textContent = item.point;

          const count = document.createElement("span");
          count.textContent = `${item.count} ${item.count === 1 ? "vote" : "votes"}`;

          row.append(point, count);
          return row;
        })
      : [document.createElement("div")]),
  );
  if (!session.distribution.length) {
    voteDistribution.firstElementChild.className = "distribution-empty";
    voteDistribution.firstElementChild.textContent = session.revealed ? "No votes yet" : "Hidden until reveal";
  }
  storyCount.textContent = `${session.stories.length}`;

  storyList.replaceChildren(
    ...session.stories.map((story, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `story-item${story.active ? " active" : ""}`;
      button.addEventListener("click", () => {
        selectedVote = null;
        send({ type: "selectStory", storyId: story.id });
      });

      const title = document.createElement("div");
      title.className = "story-item-title";
      title.textContent = story.title.trim() || `Story ${index + 1}`;

      const meta = document.createElement("div");
      meta.className = "story-item-meta";
      if (story.active) {
        meta.textContent = "Estimating now";
      } else if (story.estimate) {
        meta.textContent = `Pointed ${story.estimate}`;
      } else {
        meta.textContent = "Ready";
      }

      button.append(title, meta);
      return button;
    }),
  );

  participants.replaceChildren(
    ...session.participants.map((person) => {
      const card = document.createElement("article");
      card.className = `participant${person.connected ? "" : " offline"}`;

      const header = document.createElement("div");
      header.className = "participant-name";
      const name = document.createElement("span");
      name.textContent = person.name;
      const badge = document.createElement("span");
      badge.className = `badge${person.connected ? " online" : ""}`;
      header.append(name, badge);

      const vote = document.createElement("div");
      vote.className = `vote${person.hasVoted ? " ready" : ""}`;
      vote.textContent = session.revealed ? person.vote || "No vote" : person.hasVoted ? "Ready" : "Thinking";
      card.append(header, vote);
      return card;
    }),
  );
}

function renderRetro(session) {
  canManage = session.canManage;
  roomView.classList.add("hidden");
  retroView.classList.remove("hidden");
  revealRetroButton.disabled = !canManage || session.retroRevealed;
  revealRetroButton.textContent = session.retroRevealed ? "Board revealed" : "Reveal board";
  retroPrivacyNotice.textContent = session.retroRevealed
    ? "The retro board is visible to everyone."
    : canManage
      ? "You can see all private cards. Reveal the board when the team is ready to discuss."
      : "Your cards are private until the facilitator reveals the board.";

  Object.values(retroColumns).forEach((column) => column.replaceChildren());
  session.retroItems.forEach((item) => {
    const card = document.createElement("div");
    card.className = "retro-item";

    const text = document.createElement("p");
    text.textContent = item.text;

    const author = document.createElement("span");
    author.textContent = item.author;

    card.append(text, author);
    retroColumns[item.category]?.append(card);
  });

  Object.entries(retroColumns).forEach(([category, column]) => {
    if (!column.children.length) {
      const empty = document.createElement("div");
      empty.className = "retro-empty";
      empty.textContent = "No notes yet";
      column.append(empty);
    }
  });
}

createSessionButton.addEventListener("click", async () => {
  await createSession("pointing");
  startView.classList.add("hidden");
  joinView.classList.remove("hidden");
  nameInput.focus();
  showToast("Session link created");
});

createRetroButton.addEventListener("click", async () => {
  await createSession("retro");
  startView.classList.add("hidden");
  joinView.classList.remove("hidden");
  nameInput.focus();
  showToast("Retro link created");
});

joinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  participantName = nameInput.value.trim();
  if (!participantName) {
    return;
  }
  localStorage.setItem("sprint-room-name", participantName);
  joinView.classList.add("hidden");
  if (sessionMode === "retro") {
    retroView.classList.remove("hidden");
  } else {
    roomView.classList.remove("hidden");
  }
  connect();
});

document.querySelectorAll(".retro-form").forEach((form) => {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = form.querySelector("textarea");
    send({ type: "addRetroItem", category: form.dataset.category, text: input.value });
    input.value = "";
  });
});

storyTitle.addEventListener("input", () => {
  if (!canManage) {
    return;
  }
  window.clearTimeout(titleTimer);
  titleTimer = window.setTimeout(() => send({ type: "title", title: storyTitle.value }), 250);
});

storyDescription.addEventListener("input", () => {
  if (!canManage) {
    return;
  }
  window.clearTimeout(descriptionTimer);
  descriptionTimer = window.setTimeout(
    () => send({ type: "description", description: storyDescription.value }),
    250,
  );
});

storyForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!canManage) {
    return;
  }
  send({
    type: "addStory",
    title: newStoryTitle.value,
    description: newStoryDescription.value,
  });
  newStoryTitle.value = "";
  newStoryDescription.value = "";
});

revealButton.addEventListener("click", () => send({ type: "reveal" }));
resetButton.addEventListener("click", () => {
  selectedVote = null;
  send({ type: "reset" });
});
nextStoryButton.addEventListener("click", () => {
  selectedVote = null;
  send({ type: "next" });
});

copyLinkButton.addEventListener("click", async () => {
  await navigator.clipboard.writeText(shareUrl());
  showToast("Session link copied");
});

newSessionButton.addEventListener("click", async () => {
  if (socket) {
    shouldReconnect = false;
    socket.close();
  }
  selectedVote = null;
  await createSession();
  connect();
  showToast("New session ready");
});

copyRetroLinkButton.addEventListener("click", async () => {
  await navigator.clipboard.writeText(shareUrl());
  showToast("Session link copied");
});

revealRetroButton.addEventListener("click", () => send({ type: "revealRetro" }));

newRetroSessionButton.addEventListener("click", async () => {
  if (socket) {
    shouldReconnect = false;
    socket.close();
  }
  await createSession("retro");
  connect();
  showToast("New retro ready");
});
