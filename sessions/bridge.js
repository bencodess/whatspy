
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, proto, prepareWAMessageMedia } = require('@whiskeysockets/baileys');

let sock = null;
let eventHandlers = {};

function sendResponse(id, success, data) {
    console.log(JSON.stringify({ type: 'response', id, success, data, error: null }));
}

function sendEvent(type, data) {
    console.log(JSON.stringify({ type: 'event', event: type, data }));
}

async function handleCommand(cmd) {
    const { id, action, args } = cmd;
    
    try {
        switch(action) {
            case 'connect':
                const { state, saveCreds } = await useMultiFileAuthState(args.sessionDir);
                const { version } = await fetchLatestBaileysVersion();
                
                sock = makeWASocket({
                    version,
                    auth: state,
                    browser: [args.browser, 'Chrome', '120.0'],
                    headless: args.headless !== false,
                });

                sock.ev.on('connection.update', (update) => {
                    if (update.connection === 'open') {
                        sendEvent('connected', { jid: sock.user?.jid });
                    }
                    if (update.connection === 'close') {
                        sendEvent('disconnected', { reason: update.lastDisconnect?.error?.message });
                    }
                    if (update.qr) {
                        sendEvent('qr', { qr: update.qr });
                        if (eventHandlers['qr'] && eventHandlers['qr'].length > 0) {
                            eventHandlers['qr'][0](update.qr);
                        }
                    }
                });

                sock.ev.on('creds.update', saveCreds);
                
                sock.ev.on('messages.upsert', ({ messages }) => {
                    messages.forEach(msg => {
                        if (msg.message) {
                            sendEvent('message', {
                                key: msg.key,
                                message: msg.message,
                                messageTimestamp: msg.messageTimestamp,
                                pushName: msg.pushName,
                                participant: msg.participant,
                                jid: msg.key.remoteJid,
                            });
                        }
                    });
                });

                sock.ev.on('contacts.upsert', (contacts) => {
                    sendEvent('contacts_update', contacts);
                });

                sock.ev.on('groups.update', (groups) => {
                    sendEvent('groups_update', groups);
                });

                sock.ev.on('group-participants.update', (update) => {
                    sendEvent('group_participants_update', update);
                });

                sendResponse(id, true, { status: 'connecting' });
                break;

            case 'send_text':
                const jid = args.jid;
                const text = args.text;
                const options = args.options || {};
                await sock.sendMessage(jid, { text }, options);
                sendResponse(id, true, { status: 'sent' });
                break;

            case 'send_image':
                const imgJid = args.jid;
                const imgUrl = args.url;
                const imgCaption = args.caption;
                const imgOptions = args.options || {};
                const imgBuffer = await fetch(imgUrl).then(r => r.buffer());
                await sock.sendMessage(imgJid, { image: imgBuffer, caption: imgCaption }, imgOptions);
                sendResponse(id, true, { status: 'sent' });
                break;

            case 'send_video':
                const vidJid = args.jid;
                const vidUrl = args.url;
                const vidCaption = args.caption;
                const vidOptions = args.options || {};
                const vidBuffer = await fetch(vidUrl).then(r => r.buffer());
                await sock.sendMessage(vidJid, { video: vidBuffer, caption: vidCaption }, vidOptions);
                sendResponse(id, true, { status: 'sent' });
                break;

            case 'send_document':
                const docJid = args.jid;
                const docUrl = args.url;
                const docFilename = args.filename;
                const docOptions = args.options || {};
                const docBuffer = await fetch(docUrl).then(r => r.buffer());
                await sock.sendMessage(docJid, { document: docBuffer, fileName: docFilename }, docOptions);
                sendResponse(id, true, { status: 'sent' });
                break;

            case 'reply':
                const replyJid = args.jid;
                const replyText = args.text;
                const replyTo = args.quotedMessageId;
                const replyOptions = args.options || {};
                await sock.sendMessage(replyJid, { text: replyText }, { ...replyOptions, quoted: { key: { id: replyTo } } });
                sendResponse(id, true, { status: 'sent' });
                break;

            case 'get_contacts':
                const contacts = Object.values(sock.store?.contacts || {});
                sendResponse(id, true, { contacts });
                break;

            case 'get_contact':
                const contactJid = args.jid;
                const contact = sock.store?.contacts?.[contactJid];
                sendResponse(id, true, { contact });
                break;

            case 'get_groups':
                const groups = Object.values(sock.store?.chats || {}).filter(c => c.jid?.endsWith('@g.us'));
                sendResponse(id, true, { groups });
                break;

            case 'get_group_metadata':
                const groupJid = args.jid;
                const metadata = await sock.groupMetadata(groupJid);
                sendResponse(id, true, { metadata });
                break;

            case 'create_group':
                const groupName = args.name;
                const groupParticipants = args.participants || [];
                const group = await sock.groupCreate(groupName, groupParticipants);
                sendResponse(id, true, { group });
                break;

            case 'add_participant':
                await sock.groupParticipantsUpdate(args.jid, args.participants, 'add');
                sendResponse(id, true, { status: 'added' });
                break;

            case 'remove_participant':
                await sock.groupParticipantsUpdate(args.jid, args.participants, 'remove');
                sendResponse(id, true, { status: 'removed' });
                break;

            case 'promote_participant':
                await sock.groupParticipantsUpdate(args.jid, args.participants, 'promote');
                sendResponse(id, true, { status: 'promoted' });
                break;

            case 'demote_participant':
                await sock.groupParticipantsUpdate(args.jid, args.participants, 'demote');
                sendResponse(id, true, { status: 'demoted' });
                break;

            case 'leave_group':
                await sock.groupLeave(args.jid);
                sendResponse(id, true, { status: 'left' });
                break;

            case 'update_group_name':
                await sock.groupUpdateSubject(args.jid, args.name);
                sendResponse(id, true, { status: 'updated' });
                break;

            case 'update_group_description':
                await sock.groupUpdateDescription(args.jid, args.description);
                sendResponse(id, true, { status: 'updated' });
                break;

            case 'get_avatar':
                const avatarJid = args.jid;
                const avatarUrl = await sock.profilePictureUrl(avatarJid, 'image');
                sendResponse(id, true, { url: avatarUrl });
                break;

            case 'set_avatar':
                await sock.updateProfilePicture(args.jid, args.url);
                sendResponse(id, true, { status: 'updated' });
                break;

            case 'block_contact':
                await sock.updateBlockStatus(args.jid, 'block');
                sendResponse(id, true, { status: 'blocked' });
                break;

            case 'unblock_contact':
                await sock.updateBlockStatus(args.jid, 'unblock');
                sendResponse(id, true, { status: 'unblocked' });
                break;

            case 'get_blocklist':
                const blocklist = await sock.fetchBlocklist();
                sendResponse(id, true, { blocklist });
                break;

            case 'mark_read':
                await sock.chatModify({ markRead: true }, args.jid);
                sendResponse(id, true, { status: 'marked' });
                break;

            case 'delete_message':
                await sock.sendMessage(args.jid, { delete: { id: args.messageId } });
                sendResponse(id, true, { status: 'deleted' });
                break;

            case 'react':
                await sock.sendMessage(args.jid, { react: { text: args.emoji, key: { id: args.messageId } } });
                sendResponse(id, true, { status: 'reacted' });
                break;

            case 'get_my_number':
                sendResponse(id, true, { jid: sock.user?.jid, name: sock.user?.name });
                break;

            case 'logout':
                await sock.logout();
                sendResponse(id, true, { status: 'logged_out' });
                break;

            case 'disconnect':
                sock?.end(undefined);
                sendResponse(id, true, { status: 'disconnected' });
                break;

            default:
                sendResponse(id, false, null, 'Unknown action');
        }
    } catch (error) {
        console.error(JSON.stringify({ type: 'response', id, success: false, data: null, error: error.message }));
    }
}

process.stdin.on('data', (data) => {
    const lines = data.toString().split('\n').filter(l => l.trim());
    lines.forEach(line => {
        try {
            const cmd = JSON.parse(line);
            handleCommand(cmd);
        } catch (e) {
            console.error(JSON.stringify({ type: 'error', error: 'Invalid JSON' }));
        }
    });
});

process.on('SIGTERM', () => {
    if (sock) sock.end(undefined);
    process.exit(0);
});
