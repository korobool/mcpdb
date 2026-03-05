import { useEffect } from 'react'
import { Header } from '@/components/layout/Header'
import { LeftSidebar } from '@/components/layout/LeftSidebar'
import { RightSidebar } from '@/components/layout/RightSidebar'
import { ChatArea } from '@/components/chat/ChatArea'
import { useSourceStore } from '@/stores/sourceStore'
import { useChatStore } from '@/stores/chatStore'
import { useConfigStore } from '@/stores/configStore'

export default function App() {
  const fetchSources = useSourceStore(s => s.fetchSources)
  const connect = useChatStore(s => s.connect)
  const { fetchLLMConfig, fetchProviders, setTheme } = useConfigStore()

  useEffect(() => {
    setTheme(window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    fetchSources()
    fetchLLMConfig()
    fetchProviders()
    connect()
  }, [])

  return (
    <>
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <LeftSidebar />
        <ChatArea />
        <RightSidebar />
      </div>
    </>
  )
}
