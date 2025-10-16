import { useParams } from 'react-router-dom';
import './ProjectDashboardPage.css';

const ProjectDashboardPage = () => {
  const { projectId } = useParams();

  return (
    <div className="project-dashboard">
      <h1>Dashboard projektu</h1>
      <p>
        Detail projektu s ID <strong>{projectId}</strong> bude brzy k dispozici.
      </p>
    </div>
  );
};

export default ProjectDashboardPage;
