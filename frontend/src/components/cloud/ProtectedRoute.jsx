import { Navigate } from 'react-router-dom';
import { session } from '@/services/api';

/**
 * Keeps signed-out visitors off the dashboard.
 *
 * A convenience, not a security boundary: the token in localStorage is
 * checked here only to avoid rendering a page whose every request would
 * immediately 401. The engine authorises each request on its own, so deleting
 * this guard would expose nothing.
 */
const ProtectedRoute = ({ children }) =>
  session.get() ? children : <Navigate to="/login" replace />;

export default ProtectedRoute;
