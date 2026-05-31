# Note: 
# 0 | = System messages
# 1 | = Bot messages like received messages, sent messages, etc.
# 2 | = Error messages related to Bot
# 3 | = Unidentified

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
        print(f"1 | Message from: {msg.jid}: {msg.text}")

        if msg.text and msg.text.lower() == "9j2k5m1x7f3q6r8h4p2d0b5g1n9v3c7w2t4s8l6x1m4k9f2q5r7h3p8d1b6g0j4v2c9w5t1s3n7l":
            client.send_text(msg.jid, "Test")

        elif msg.text and msg.text.lower() == "7x2m9k5f1q3r8h4p6d0b2g5j9v1c8w3t4s7n2l6x1m4k9f2q5r7h3p8d1b6g0j4v2c9w5t1s3n7l":
            client.send_text(msg.jid, "Test2")

    @client.on_qr
    def handle_qr(qr):
        from whatsspy.client import render_qr_ascii
        print("0 |Scan this QR code:")
        print(render_qr_ascii(qr))

    @client.on_connected
    def handle_connected(jid):
        print(f"0 |Connected! Your JID: {jid}")

    @client.on_disconnected
    def handle_disconnected(reason):
        print(f"0 |Disconnected: {reason}")

    print("0 |Connecting to WhatsApp...")
    client.connect()

    print("0 |Connected! Waiting for messages...")

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n0 |Disconnecting...")
        client.disconnect()


if __name__ == "__main__":
    main()
