import process from 'node:process';
import makeWASocket, { DisconnectReason, useMultiFileAuthState } from '@whiskeysockets/baileys';
import Pino from 'pino';

const authDir = process.env.POST_OFFICE_WHATSAPP_AUTH_DIR ?? './state/whatsapp-auth';
const logger = Pino({ level: process.env.POST_OFFICE_WHATSAPP_LOG_LEVEL ?? 'warn' });

function emit(event) {
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  const socket = makeWASocket({ auth: state, logger });

  socket.ev.on('creds.update', saveCreds);
  socket.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      emit({ type: 'qr', qr });
    }
    if (connection === 'close') {
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      if (statusCode !== DisconnectReason.loggedOut) {
        start().catch((error) => {
          console.error(error);
          process.exit(1);
        });
      }
    }
  });

  socket.ev.on('messages.upsert', ({ messages }) => {
    for (const message of messages) {
      if (!message.message || message.key.fromMe) {
        continue;
      }
      emit({ type: 'message', ...message });
    }
  });
}

start().catch((error) => {
  console.error(error);
  process.exit(1);
});
