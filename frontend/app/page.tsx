'use client'

import { useState, useEffect, useRef } from 'react'
import { DashboardLayout } from '@/components/DashboardLayout'
import { TransformationsTab } from '@/components/TransformationsTab'
import { DestinationsTab } from '@/components/DestinationsTab'
import { DeliveryLogsTab } from '@/components/DeliveryLogsTab'

type Tab = 'transformations' | 'destinations' | 'delivery-logs'

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<Tab>('transformations')
  const [transformations, setTransformations] = useState<any[]>([])
  const [destinations, setDestinations] = useState<any[]>([])
  const [bins, setBins] = useState<any[]>([])

  useEffect(() => {
    fetchTransformations()
    fetchDestinations()
    fetchBins()
  }, [])

  const fetchTransformations = async () => {
    try {
      const res = await fetch('/api/v1/transformations')
      if (res.ok) {
        const data = await res.json()
        setTransformations(data)
      }
    } catch (e) {
      console.error('Failed to fetch transformations:', e)
    }
  }

  const fetchDestinations = async () => {
    try {
      const res = await fetch('/api/v1/destinations')
      if (res.ok) {
        const data = await res.json()
        setDestinations(data)
      }
    } catch (e) {
      console.error('Failed to fetch destinations:', e)
    }
  }

  const fetchBins = async () => {
    try {
      const res = await fetch('/api/v1/bins')
      if (res.ok) {
        const data = await res.json()
        setBins(data)
      }
    } catch (e) {
      console.error('Failed to fetch bins:', e)
    }
  }

  const handleTransformationSaved = () => {
    fetchTransformations()
  }

  const handleDestinationSaved = () => {
    fetchDestinations()
  }

  return (
    <DashboardLayout
      activeTab={activeTab}
      onTabChange={setActiveTab}
      transformations={transformations}
      destinations={destinations}
      bins={bins}
      onTransformationSaved={handleTransformationSaved}
      onDestinationSaved={handleDestinationSaved}
    >
      {activeTab === 'transformations' && (
        <TransformationsTab
          transformations={transformations}
          onSaved={handleTransformationSaved}
        />
      )}
      {activeTab === 'destinations' && (
        <DestinationsTab
          destinations={destinations}
          bins={bins}
          transformations={transformations}
          onSaved={handleDestinationSaved}
        />
      )}
      {activeTab === 'delivery-logs' && (
        <DeliveryLogsTab destinations={destinations} />
      )}
    </DashboardLayout>
  )
}