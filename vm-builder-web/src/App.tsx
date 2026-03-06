import { useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Dashboard from './pages/Dashboard'
import InitSecrets from './pages/InitSecrets'
import VmCreate from './pages/VmCreate'
import VmList from './pages/VmList'
import VmDetail from './pages/VmDetail'
import Hypervisor from './pages/Hypervisor'
import HypervisorList from './pages/HypervisorList'
import HypervisorDetail from './pages/HypervisorDetail'
import Registry from './pages/Registry'
import Sidebar, { NavItem } from './components/Sidebar'
import { ToastProvider, useToast } from './components/Toast'
import ErrorBoundary from './components/ErrorBoundary'
import { ApiError } from './api/errors'

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Dashboard', subtitle: 'System health and quick actions' },
  { to: '/init', label: 'Init Secrets', subtitle: 'Configure credentials for all providers' },
  { to: '/vm/create', label: 'Create VM', subtitle: 'Build and provision new virtual machines' },
  { to: '/vms', label: 'VMs', subtitle: 'Manage, deploy, and monitor your fleet' },
  { to: '/hypervisors', label: 'Hypervisors', subtitle: 'View and manage hypervisor hosts' },
  { to: '/hypervisor', label: 'Bootstrap', subtitle: 'Bootstrap new hypervisor hosts' },
  { to: '/registry', label: 'Registry', subtitle: 'Browse available apps and dependencies' },
]

function AppInner() {
  const toast = useToast()

  const [queryClient] = useState(() =>
    new QueryClient({
      defaultOptions: {
        mutations: {
          onError: (error) => {
            if (error instanceof ApiError) {
              toast.error(error.message, { hint: error.hint })
            } else if (error instanceof Error) {
              toast.error(error.message)
            }
          },
        },
        queries: {
          retry: 1,
        },
      },
    }),
  )

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-screen bg-gray-50 flex">
          <Sidebar items={NAV_ITEMS} />
          <main className="flex-1 max-w-6xl px-8 py-8">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/init" element={<InitSecrets />} />
              <Route path="/vm/create" element={<VmCreate />} />
              <Route path="/vms" element={<VmList />} />
              <Route path="/vms/:name" element={<VmDetail />} />
              <Route path="/hypervisors" element={<HypervisorList />} />
              <Route path="/hypervisors/:name" element={<HypervisorDetail />} />
              <Route path="/hypervisor" element={<Hypervisor />} />
              <Route path="/registry" element={<Registry />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <AppInner />
      </ToastProvider>
    </ErrorBoundary>
  )
}
