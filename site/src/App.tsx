import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom'

import { HomePage } from '@/pages/HomePage'

const queryClient = new QueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </QueryClientProvider>
  )
}
