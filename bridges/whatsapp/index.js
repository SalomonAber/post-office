import process from 'node:process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import makeWASocket, {
  Browsers,
  DisconnectReason,
  downloadMediaMessage,
  getContentType,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys';
import Pino from 'pino';

const authDir = process.env.POST_OFFICE_WHATSAPP_AUTH_DIR ?? './state/whatsapp-auth';
const mediaDir = process.env.POST_OFFICE_WHATSAPP_MEDIA_DIR ?? './state/media/whatsapp';
const browserName = process.env.POST_OFFICE_WHATSAPP_BROWSER ?? 'Desktop';
const includeOwnMessages = process.env.POST_OFFICE_WHATSAPP_INCLUDE_OWN_MESSAGES === '1';
const ignoreMutedChats = process.env.POST_OFFICE_WHATSAPP_IGNORE_MUTED_CHATS === '1';
const logger = Pino(
  { level: process.env.POST_OFFICE_WHATSAPP_LOG_LEVEL ?? 'warn' },
  Pino.destination(2),
);
let socket;
const mutedChats = new Map();

function emit(event) {
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

function log(message) {
  process.stderr.write(`${message}\n`);
}

function normalizeTimestamp(timestamp) {
  if (!timestamp) {
    return undefined;
  }
  if (typeof timestamp === 'number') {
    return timestamp;
  }
  if (typeof timestamp === 'string') {
    return Number.parseInt(timestamp, 10);
  }
  if (typeof timestamp === 'object' && typeof timestamp.toNumber === 'function') {
    return timestamp.toNumber();
  }
  return undefined;
}

async function normalizeMessage(message) {
  const key = message.key ?? {};
  const chatId = key.remoteJid;
  const senderId = key.participant ?? chatId;
  const attachments = await downloadImageAttachments(message);

  return {
    type: 'message',
    chatId,
    senderId,
    senderName: message.pushName,
    key,
    chatMuted: chatIsMuted(chatId),
    message: message.message,
    messageTimestamp: normalizeTimestamp(message.messageTimestamp),
    attachments,
  };
}

function rememberMutedChats(chats) {
  for (const chat of chats ?? []) {
    const chatId = chat.id ?? chat.jid;
    if (!chatId || !('muteEndTime' in chat)) {
      continue;
    }
    const muteEndTime = normalizeTimestamp(chat.muteEndTime);
    if (muteEndTime && muteEndTime > 0) {
      mutedChats.set(chatId, muteEndTime);
    } else {
      mutedChats.delete(chatId);
    }
  }
}

function chatIsMuted(chatId) {
  const muteEndTime = mutedChats.get(chatId);
  if (!muteEndTime) {
    return false;
  }
  if (muteEndTime <= Math.floor(Date.now() / 1000)) {
    mutedChats.delete(chatId);
    return false;
  }
  return true;
}

async function downloadImageAttachments(message) {
  const contentType = getContentType(message.message);
  if (contentType !== 'imageMessage') {
    return [];
  }

  const image = message.message.imageMessage;
  const messageId = message.key?.id ?? `${Date.now()}`;
  const contentTypeValue = image.mimetype ?? 'image/jpeg';
  const extension = imageExtension(contentTypeValue);
  const filename = `${safeName(messageId)}.${extension}`;
  const directory = path.join(mediaDir, safeName(message.key?.remoteJid ?? 'unknown'), safeName(messageId));
  const localPath = path.join(directory, filename);
  await mkdir(directory, { recursive: true });
  const buffer = await downloadMediaMessage(message, 'buffer', {}, { logger });
  await writeFile(localPath, buffer);

  return [
    {
      contentType: contentTypeValue,
      filename,
      localPath,
      sizeBytes: buffer.length,
      sourceId: image.mediaKeyTimestamp ? String(image.mediaKeyTimestamp) : messageId,
    },
  ];
}

function imageExtension(contentType) {
  switch (contentType.toLowerCase()) {
    case 'image/png':
      return 'png';
    case 'image/webp':
      return 'webp';
    case 'image/gif':
      return 'gif';
    default:
      return 'jpg';
  }
}

function safeName(value) {
  return String(value).replace(/[^A-Za-z0-9._-]/g, '_');
}

function normalizeDisconnect(lastDisconnect) {
  const error = lastDisconnect?.error;
  return {
    statusCode: error?.output?.statusCode,
    reason: error?.output?.payload?.error,
    message: error?.message,
    name: error?.name,
  };
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  socket = makeWASocket({
    auth: state,
    browser: Browsers.macOS(browserName),
    logger,
    markOnlineOnConnect: false,
    syncFullHistory: false,
  });

  socket.ev.on('creds.update', saveCreds);
  socket.ev.on('messaging-history.set', ({ chats }) => rememberMutedChats(chats));
  socket.ev.on('chats.upsert', rememberMutedChats);
  socket.ev.on('chats.update', rememberMutedChats);

  socket.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      emit({ type: 'qr', qr });
    }
    if (connection === 'open') {
      emit({ type: 'ready' });
    }
    if (connection === 'close') {
      const disconnect = normalizeDisconnect(lastDisconnect);
      emit({ type: 'closed', ...disconnect });
      const statusCode = disconnect.statusCode;
      process.exit(statusCode === DisconnectReason.loggedOut ? 0 : 75);
    }
  });

  socket.ev.on('messages.upsert', async ({ messages }) => {
    for (const message of messages) {
      if (!message.message || (message.key.fromMe && !includeOwnMessages)) {
        continue;
      }
      if (ignoreMutedChats && chatIsMuted(message.key.remoteJid)) {
        continue;
      }
      try {
        emit(await normalizeMessage(message));
      } catch (error) {
        emit({
          type: 'media-error',
          message: error.message,
          messageId: message.key?.id,
        });
        log(`WhatsApp media download failed: ${error.stack ?? String(error)}`);
      }
    }
  });
}

process.on('SIGINT', () => {
  socket?.end?.();
  process.exit(0);
});

process.on('SIGTERM', () => {
  socket?.end?.();
  process.exit(0);
});

start().catch((error) => {
  log(error.stack ?? String(error));
  process.exit(1);
});
