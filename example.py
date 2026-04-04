#!/usr/bin/env python3
"""
WhatsSpy - Example Usage

This script demonstrates how to use the WhatsSpy library to interact with WhatsApp.
"""

from whatsspy import WhatsSpyClient


def main():
    client = WhatsSpyClient(
        session_name="my_session",
        session_dir="./sessions",
        headless=False,
        debug=True,
    )

    @client.on_message
    def handle_message(msg):
        print(f"Received message from {msg.jid}: {msg.text}")

        if msg.text and msg.text.lower() == "hello":
            client.send_text(msg.jid, "Hello! How can I help you?")

        elif msg.text and msg.text.lower() == "ping":
            client.send_text(msg.jid, "Pong!")

    @client.on_qr
    def handle_qr(qr):
        from whatsspy.client import render_qr_ascii
        print("Scan this QR code:")
        print(render_qr_ascii(qr))

    @client.on_connected
    def handle_connected(jid):
        print(f"Connected! Your JID: {jid}")

    @client.on_disconnected
    def handle_disconnected(reason):
        print(f"Disconnected: {reason}")

    print("Connecting to WhatsApp...")
    client.connect()

    print("Connected! Waiting for messages...")

    try:
        import time
        while client.is_connected:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDisconnecting...")
        client.disconnect()


if __name__ == "__main__":
    main()
