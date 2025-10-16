import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const getProjects = () => apiClient.get('/projects/');

export const createProject = (projectData) => apiClient.post('/projects/', projectData);

export default apiClient;
