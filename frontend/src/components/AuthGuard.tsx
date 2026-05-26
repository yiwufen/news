import { Navigate, useLocation } from 'react-router-dom'
import { getAccessToken } from '../api/client'

interface Props {
  children: React.ReactNode
}

export default function AuthGuard({ children }: Props) {
  const location = useLocation()
  if (!getAccessToken()) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  return <>{children}</>
}
