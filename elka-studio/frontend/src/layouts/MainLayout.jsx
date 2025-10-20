import { NavLink, Outlet, useMatch } from 'react-router-dom';
import './MainLayout.css';

const navLinkClass = ({ isActive }) =>
  `sidebar__link${isActive ? ' active' : ''}`;

const projectNavLinkClass = ({ isActive }) =>
  `project-tabs__link${isActive ? ' active' : ''}`;

const MainLayout = () => {
  const projectMatch = useMatch('/projects/:projectId/*');
  const projectRootMatch = useMatch('/projects/:projectId');
  const projectId = projectMatch?.params?.projectId || projectRootMatch?.params?.projectId;

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar__brand">
          <span className="sidebar__logo">eLKA Studio</span>
        </div>
        <nav className="sidebar__nav">
          <NavLink to="/" end className={navLinkClass}>
            Projects
          </NavLink>
          <NavLink to="/settings" className={navLinkClass}>
            <span aria-hidden>⚙️</span>
            <span className="sidebar__link-text">Settings</span>
          </NavLink>
        </nav>
      </aside>
      <main className="content">
        {projectId ? (
          <div className="project-tabs" role="tablist" aria-label="Project sections">
            <NavLink to={`/projects/${projectId}`} end className={projectNavLinkClass}>
              Studio
            </NavLink>
            <NavLink
              to={`/projects/${projectId}/browse`}
              className={projectNavLinkClass}
            >
              Prohlížeč
            </NavLink>
          </div>
        ) : null}
        <Outlet />
      </main>
    </div>
  );
};

export default MainLayout;
