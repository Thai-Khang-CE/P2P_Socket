(function () {
    const state = {
        username: localStorage.getItem("chat_username") || "alice",
        channel: localStorage.getItem("chat_channel") || "general",
        lastMessageId: 0,
        lastNotificationId: 0,
        polling: null
    };

    const els = {
        username: document.getElementById("username"),
        saveName: document.getElementById("save-name"),
        channelName: document.getElementById("channel-name"),
        createChannel: document.getElementById("create-channel"),
        joinChannel: document.getElementById("join-channel"),
        leaveChannel: document.getElementById("leave-channel"),
        channelList: document.getElementById("channel-list"),
        channelCount: document.getElementById("channel-count"),
        peerList: document.getElementById("peer-list"),
        peerCount: document.getElementById("peer-count"),
        activeChannel: document.getElementById("active-channel"),
        statusLine: document.getElementById("status-line"),
        notifications: document.getElementById("notifications"),
        messageWindow: document.getElementById("message-window"),
        messageForm: document.getElementById("message-form"),
        messageInput: document.getElementById("message-input")
    };

    function formBody(data) {
        return new URLSearchParams(data).toString();
    }

    async function api(path, options) {
        const response = await fetch(path, options);
        if (!response.ok) {
            const error = new Error(`HTTP ${response.status}`);
            error.status = response.status;
            throw error;
        }
        return response.json();
    }

    function setStatus(text) {
        els.statusLine.textContent = text;
    }

    function normalizeChannelName(value) {
        return (value || "general").trim().toLowerCase().replace(/\s+/g, "-");
    }

    function renderChannels(channels) {
        els.channelList.textContent = "";
        els.channelCount.textContent = String(channels.length);
        channels.forEach((channel) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "channel-button";
            if (channel.name === state.channel) {
                button.classList.add("active");
            }
            button.innerHTML = `
                <span># ${escapeHtml(channel.name)}</span>
                <span>${channel.member_count}</span>
            `;
            button.addEventListener("click", () => switchChannel(channel.name));
            els.channelList.appendChild(button);
        });
    }

    function renderPeers(peers) {
        els.peerList.textContent = "";
        els.peerCount.textContent = String(peers.length);
        if (!peers.length) {
            const empty = document.createElement("li");
            empty.textContent = "No peers yet";
            els.peerList.appendChild(empty);
            return;
        }
        peers.forEach((peer) => {
            const item = document.createElement("li");
            item.textContent = peer;
            els.peerList.appendChild(item);
        });
    }

    function renderMessages(messages, replace) {
        if (replace) {
            els.messageWindow.textContent = "";
        }
        if (messages.length) {
            const empty = els.messageWindow.querySelector(".empty-state");
            if (empty) {
                empty.remove();
            }
        }
        messages.forEach((message) => {
            const row = document.createElement("article");
            row.className = message.system ? "message system" : "message";
            if (message.username === state.username) {
                row.classList.add("own");
            }
            const date = new Date(message.timestamp * 1000).toLocaleTimeString();
            const initial = escapeHtml(String(message.username || "?").slice(0, 1).toUpperCase());
            row.innerHTML = `
                <div class="avatar">${initial}</div>
                <div class="message-body">
                    <div class="message-meta">${escapeHtml(message.username)} - ${date}</div>
                    <div class="message-text">${escapeHtml(message.text)}</div>
                </div>
            `;
            els.messageWindow.appendChild(row);
            state.lastMessageId = Math.max(state.lastMessageId, message.id);
        });
        if (!els.messageWindow.children.length) {
            const empty = document.createElement("div");
            empty.className = "empty-state";
            empty.innerHTML = `
                <strong>No messages here yet.</strong>
                <span>Create a channel, invite a second browser, and start the first thread.</span>
            `;
            els.messageWindow.appendChild(empty);
        }
        if (messages.length) {
            els.messageWindow.scrollTop = els.messageWindow.scrollHeight;
        }
    }

    function renderNotifications(notifications) {
        if (!notifications.length) {
            els.notifications.textContent = "";
            return;
        }
        const latest = notifications[notifications.length - 1];
        els.notifications.textContent = `New in #${latest.channel}: ${latest.username}`;
        if (latest.id > state.lastNotificationId) {
            state.lastNotificationId = latest.id;
            if ("Notification" in window && Notification.permission === "granted") {
                new Notification(`#${latest.channel}`, {
                    body: `${latest.username}: ${latest.text}`
                });
            }
        }
    }

    async function refresh(replace) {
        const query = new URLSearchParams({
            username: state.username,
            channel: state.channel,
            since: replace ? "0" : String(state.lastMessageId)
        });
        const data = await api(`/chat-state?${query.toString()}`);
        els.activeChannel.textContent = `# ${data.active_channel}`;
        renderChannels(data.channels);
        renderPeers(data.peers);
        renderMessages(data.messages, replace);
        renderNotifications(data.notifications);
        setStatus(`Signed in as ${state.username}`);
    }

    async function switchChannel(channel) {
        state.channel = normalizeChannelName(channel);
        state.lastMessageId = 0;
        localStorage.setItem("chat_channel", state.channel);
        els.channelName.value = state.channel;
        await refresh(true);
    }

    async function createChannel() {
        const channel = normalizeChannelName(els.channelName.value);
        const request = {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: formBody({username: state.username, channel})
        };
        try {
            await api("/channel-create", request);
        } catch (error) {
            if (error.status !== 404) {
                throw error;
            }
            await api("/channel-join", request);
        }
        await switchChannel(channel);
        setStatus(`Created or joined #${channel}`);
    }

    async function joinChannel() {
        const channel = normalizeChannelName(els.channelName.value);
        await api("/channel-join", {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: formBody({username: state.username, channel})
        });
        await switchChannel(channel);
    }

    async function leaveChannel() {
        await api("/channel-leave", {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: formBody({username: state.username, channel: state.channel})
        });
        await switchChannel("general");
    }

    async function sendMessage(event) {
        event.preventDefault();
        const message = els.messageInput.value.trim();
        if (!message) {
            return;
        }
        els.messageInput.value = "";
        await api("/chat-message", {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: formBody({
                username: state.username,
                channel: state.channel,
                message
            })
        });
        await refresh(false);
    }

    function saveName() {
        state.username = els.username.value.trim() || "guest";
        localStorage.setItem("chat_username", state.username);
        state.lastMessageId = 0;
        refresh(true).catch(showError);
    }

    function showError(error) {
        setStatus(`Error: ${error.message}`);
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function start() {
        els.username.value = state.username;
        els.channelName.value = state.channel;
        els.saveName.addEventListener("click", saveName);
        els.createChannel.addEventListener("click", () => createChannel().catch(showError));
        els.joinChannel.addEventListener("click", () => joinChannel().catch(showError));
        els.leaveChannel.addEventListener("click", () => leaveChannel().catch(showError));
        els.messageForm.addEventListener("submit", (event) => {
            sendMessage(event).catch(showError);
        });
        if ("Notification" in window && Notification.permission === "default") {
            Notification.requestPermission().catch(() => {});
        }
        refresh(true).catch(showError);
        state.polling = setInterval(() => refresh(false).catch(showError), 1500);
    }

    start();
}());
