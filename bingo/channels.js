(function (global) {
  "use strict";

  class Subscription {
    constructor(consumer, identifier, channel, params, callbacks) {
      this.consumer = consumer;
      this.identifier = identifier;
      this.channel = channel;
      this.params = params;
      Object.assign(this, callbacks || {});
    }

    send(data) {
      this.consumer.send({
        command: "message",
        identifier: this.identifier,
        data: data,
      });
    }

    unsubscribe() {
      this.consumer.unsubscribe(this.identifier);
    }
  }

  class ChannelConsumer {
    constructor(path) {
      this.path = path || "/channels";
      this.socket = null;
      this.subscriptions = new Map();
      this.nextIdentifier = 1;
      this.reconnectDelay = 500;
      this.reconnectTimer = null;
    }

    subscribe(channel, params, callbacks) {
      const identifier = String(this.nextIdentifier++);
      const subscription = new Subscription(
        this,
        identifier,
        channel,
        params || {},
        callbacks,
      );
      this.subscriptions.set(identifier, subscription);
      this.connect();
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.sendSubscription(subscription);
      }
      return subscription;
    }

    connect() {
      const isConnecting = this.socket && (
        this.socket.readyState === WebSocket.OPEN ||
        this.socket.readyState === WebSocket.CONNECTING
      );
      if (isConnecting) return;

      const protocol = global.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocol}//${global.location.host}${this.path}`;
      this.socket = new WebSocket(url);
      this.socket.addEventListener("open", () => this.opened());
      this.socket.addEventListener("message", (event) => this.received(event));
      this.socket.addEventListener("close", () => this.closed());
    }

    opened() {
      this.reconnectDelay = 500;
      for (const subscription of this.subscriptions.values()) {
        this.sendSubscription(subscription);
      }
    }

    received(event) {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (_error) {
        return;
      }

      const subscription = this.subscriptions.get(message.identifier);
      if (!subscription) return;

      if (message.type === "subscribed" && subscription.connected) {
        subscription.connected();
      } else if (message.type === "message" && subscription.received) {
        subscription.received(message.event, message.data);
      } else if (message.type === "rejected") {
        this.subscriptions.delete(message.identifier);
        if (subscription.rejected) subscription.rejected(message.error);
        if (this.subscriptions.size === 0 && this.socket) this.socket.close();
      } else if (message.type === "error" && subscription.errored) {
        subscription.errored(message.error);
      }
    }

    closed() {
      this.socket = null;
      for (const subscription of this.subscriptions.values()) {
        if (subscription.disconnected) subscription.disconnected();
      }
      if (this.subscriptions.size === 0) return;

      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = setTimeout(() => this.connect(), this.reconnectDelay);
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 10000);
    }

    unsubscribe(identifier) {
      if (!this.subscriptions.has(identifier)) return;
      this.send({ command: "unsubscribe", identifier: identifier });
      this.subscriptions.delete(identifier);
      if (this.subscriptions.size === 0 && this.socket) {
        this.socket.close();
      }
    }

    sendSubscription(subscription) {
      this.send({
        command: "subscribe",
        identifier: subscription.identifier,
        channel: subscription.channel,
        params: subscription.params,
      });
    }

    send(message) {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
        throw new Error("The Bingo channel connection is not open.");
      }
      this.socket.send(JSON.stringify(message));
    }
  }

  const Bingo = global.Bingo || {};
  const script = global.document.currentScript;
  const defaultPath = script
    ? new URL(script.src, global.location.href).pathname.replace(/\.js$/, "")
    : "/channels";
  Bingo.channels = new ChannelConsumer(defaultPath);
  Bingo.ChannelConsumer = ChannelConsumer;
  global.Bingo = Bingo;
})(window);
