import { Route, Routes } from 'react-router-dom';
import MainLayout from './layouts/MainLayout';
import ProjectsPage from './pages/ProjectsPage';
import ProjectDashboardPage from './pages/ProjectDashboardPage';
import './App.css';

const App = () => (
  <Routes>
    <Route path="/" element={<MainLayout />}>
      <Route index element={<ProjectsPage />} />
      <Route path="projects/:projectId" element={<ProjectDashboardPage />} />
    </Route>
  </Routes>
);

export default App;
