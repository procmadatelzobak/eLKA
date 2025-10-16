import { API_BASE_URL } from './api';

const normalizeBaseUrl = (url) => {
  if (!url) {
    return '';
  }

  return url.replace(/\/$/, '');
};

const convertHttpToWs = (url) => {
  if (url.startsWith('https://')) {
    return url.replace('https://', 'wss://');
  }

  if (url.startsWith('http://')) {
    return url.replace('http://', 'ws://');
  }

  return url;
};

const deriveWsBaseUrl = () => {
  const envBase = import.meta.env.VITE_WS_BASE_URL;

  if (envBase) {
    return normalizeBaseUrl(envBase);
  }

  const httpBase = normalizeBaseUrl(API_BASE_URL);
  const withoutApi = httpBase.replace(/\/api\/?$/, '');

  return normalizeBaseUrl(convertHttpToWs(withoutApi));
};

const WS_BASE_URL = deriveWsBaseUrl();

export class TaskSocket {
  constructor() {
    this.socket = null;
    this.onUpdate = null;
  }

  connect(projectId, onUpdate) {
    if (!projectId) {
      throw new Error('projectId is required to establish a WebSocket connection');
    }

    if (this.socket) {
      this.disconnect();
    }

    this.onUpdate = typeof onUpdate === 'function' ? onUpdate : () => {};

    const baseUrl = WS_BASE_URL;
    const url = `${baseUrl}/ws/tasks/${projectId}`;

    this.socket = new WebSocket(url);

    this.socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        this.onUpdate(payload);
      } catch (error) {
        console.error('Failed to parse task update payload', error);
      }
    };

    this.socket.onclose = () => {
      this.socket = null;
    };

    this.socket.onerror = (error) => {
      console.error('TaskSocket encountered an error', error);
    };
  }

  disconnect() {
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
  }
}

export default TaskSocket;
