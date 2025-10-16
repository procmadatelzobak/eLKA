import axios from 'axios';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const getProjects = () => apiClient.get('/projects/');

export const createProject = (projectData) => apiClient.post('/projects/', projectData);

export const createTask = (taskData) => apiClient.post('/tasks/', taskData);

export const pauseTask = (taskId) => apiClient.post(`/tasks/${taskId}/pause`);

export const resumeTask = (taskId) => apiClient.post(`/tasks/${taskId}/resume`);

export default apiClient;
