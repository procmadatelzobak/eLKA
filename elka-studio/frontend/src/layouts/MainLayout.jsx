import { NavLink, Outlet } from 'react-router-dom';
import './MainLayout.css';

const navLinkClass = ({ isActive }) =>
  `sidebar__link${isActive ? ' active' : ''}`;

const MainLayout = () => (
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
      <Outlet />
    </main>
  </div>
);

export default MainLayout;
