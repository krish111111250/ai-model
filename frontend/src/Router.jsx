import { createBrowserRouter } from 'react-router-dom';
import LocalApp from '@/LocalApp';
import AuthPage from '@/components/cloud/AuthPage';
import DashboardHome from '@/components/cloud/DashboardHome';
import DashboardLayout from '@/components/cloud/DashboardLayout';
import LandingPage from '@/components/cloud/LandingPage';
import NotFound from '@/components/cloud/NotFound';
import ProtectedRoute from '@/components/cloud/ProtectedRoute';
import SettingsPage from '@/components/cloud/SettingsPage';

/**
 * Both products are served from one bundle: the public SaaS pages and the
 * local chat UI.
 *
 * createBrowserRouter rather than declarative <Routes> because the dashboard
 * is a layout with nested pages, and that is a `children` array here instead
 * of a second routing mechanism later.
 */
export const router = createBrowserRouter([
  { path: '/', element: <LandingPage /> },
  { path: '/login', element: <AuthPage /> },

  // Two pages under one shell: the workspace a customer uses daily, and the
  // account settings they visit occasionally. Real routes rather than tab
  // state, so /dashboard/settings can be linked to and the back button works.
  {
    path: '/dashboard',
    element: (
      <ProtectedRoute>
        <DashboardLayout />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <DashboardHome /> },
      { path: 'settings', element: <SettingsPage /> },
    ],
  },

  // Part 2, finished: talks to the local gateway on port 8001.
  { path: '/chat', element: <LocalApp /> },

  { path: '*', element: <NotFound /> },
]);
