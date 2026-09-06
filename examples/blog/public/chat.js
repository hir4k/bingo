(function () {
  "use strict";

  const form = document.querySelector("#chat-form");
  const messages = document.querySelector("#messages");
  const status = document.querySelector("#status");
  const button = form.querySelector("button");

  const chat = Bingo.channels.subscribe("ChatChannel", { room: "lobby" }, {
    connected() {
      status.textContent = "Connected to the lobby.";
      button.disabled = false;
    },

    disconnected() {
      status.textContent = "Disconnected. Reconnecting…";
      button.disabled = true;
    },

    rejected(error) {
      status.textContent = error;
      button.disabled = true;
    },

    received(event, data) {
      if (event === "validation_error") {
        status.textContent = Object.values(data.errors).flat().join(" ");
        return;
      }
      if (event !== "message") return;

      const item = document.createElement("li");
      const name = document.createElement("strong");
      name.textContent = `${data.name}: `;
      item.append(name, document.createTextNode(data.body));
      messages.append(item);
      messages.scrollTop = messages.scrollHeight;
    },
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    chat.send({ name: data.get("name"), body: data.get("body") });
    form.elements.body.value = "";
    form.elements.body.focus();
  });
})();
