'use client'

import { useState, useEffect } from 'react'
import { DashboardLayout } from '@/components/DashboardLayout'
import { TransformationsTab } from '@/components/TransformationsTab'
import { DestinationsTab } from '@/components/DestinationsTab'
import { DeliveryLogsTab } from '@/components/DeliveryLogsTab'
import {
  listTransformations,
  listDestinations,
  listBins,
  Transformation,
  Destination,
  CaptureBin,
} from '@/lib/api'

type Tab = 'transformations' | 'destinations' | 'delivery-logs'

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<Tab>('transformations')
  const [transformations, setTransformations] = useState<Transformation[]>([])
  const [destinations, setDestinations] = useState<Destination[]>([])
  const [bins, setBins] = useState<CaptureBin[]>([])

  useEffect(() => {
    fetchTransformations()
    fetchDestinations()
    fetchBins()
  }, [])

  const fetchTransformations = async () => {
    try {
      setTransformations(await listTransformations())
    } catch (e) {
      console.error('Failed to fetch transformations:', e)
    }
  }

  const fetchDestinations = async () => {
    try {
      setDestinations(await listDestinations())
    } catch (e) {
      console.error('Failed to fetch destinations:', e)
    }
  }

  const fetchBins = async () => {
    try {
      setBins(await listBins())
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
