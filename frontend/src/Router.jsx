import { createBrowserRouter } from 'react-router-dom';
import LocalApp from '@/LocalApp';
import AuthPage from '@/components/cloud/AuthPage';
import DashboardLayout from '@/components/cloud/DashboardLayout';
import LandingPage from '@/components/cloud/LandingPage';
import NotFound from '@/components/cloud/NotFound';
import ProtectedRoute from '@/components/cloud/ProtectedRoute';

/**
 * Both products are served from one bundle: the public SaaS pages and the
 * local chat UI.
 *
 * createBrowserRouter rather than declarative <Routes> because the dashboard
 * becomes a layout with nested pages (usage, API keys, docs), and that is a
 * `children` array here instead of a second routing mechanism later.
 */
export const router = createBrowserRouter([
  { path: '/', element: <LandingPage /> },
  { path: '/login', element: <AuthPage /> },

  // Nested dashboard pages get added as children of this route.
  {
    path: '/dashboard',
    element: (
      <ProtectedRoute>
        <DashboardLayout />
      </ProtectedRoute>
    ),
  },

  // Part 2, finished: talks to the local gateway on port 8001.
  { path: '/chat', element: <LocalApp /> },

  { path: '*', element: <NotFound /> },
]);
