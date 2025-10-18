import axios from 'axios';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';
export const GEMINI_API_KEY_STORAGE_KEY = 'geminiApiKey';

export const getApiClient = () => {
  const apiKey = typeof window !== 'undefined'
    ? window.localStorage.getItem(GEMINI_API_KEY_STORAGE_KEY)
    : null;

  const headers = {
    'Content-Type': 'application/json',
  };

  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }

  return axios.create({
    baseURL: API_BASE_URL,
    headers,
  });
};

export const getProjects = () => getApiClient().get('/projects/');

export const getProject = (projectId) => getApiClient().get(`/projects/${projectId}`);

export const createProject = (projectData) => getApiClient().post('/projects/', projectData);

export const createTask = (taskData) => getApiClient().post('/tasks/', taskData);

export const pauseTask = (taskId) => getApiClient().post(`/tasks/${taskId}/pause`);

export const resumeTask = (taskId) => getApiClient().post(`/tasks/${taskId}/resume`);

export const deleteTask = (taskId) => getApiClient().delete(`/tasks/${taskId}`);

export default getApiClient;
