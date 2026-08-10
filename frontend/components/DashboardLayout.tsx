'use client'

import { useState } from 'react'
import { ReactNode } from 'react'

interface DashboardLayoutProps {
  activeTab: 'transformations' | 'destinations' | 'delivery-logs'
  onTabChange: (tab: 'transformations' | 'destinations' | 'delivery-logs') => void
  transformations: any[]
  destinations: any[]
  bins: any[]
  onTransformationSaved: () => void
  onDestinationSaved: () => void
  children: ReactNode
}

const tabs = [
  { id: 'transformations', label: 'Transformations', icon: '⚙️' },
  { id: 'destinations', label: 'Destinations', icon: '🎯' },
  { id: 'delivery-logs', label: 'Delivery Logs', icon: '📊' },
] as const

export function DashboardLayout({
  activeTab,
  onTabChange,
  children,
}: DashboardLayoutProps) {
  return (
    <div className="min-h-screen bg-neutral-50">
      {/* Header */}
      <header className="bg-white border-b border-neutral-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 bg-primary-600 rounded-lg flex items-center justify-center text-white font-bold">
                🪝
              </div>
              <h1 className="text-xl font-semibold text-neutral-900">Hookrelay Dashboard</h1>
            </div>
            <nav className="flex gap-1 bg-neutral-100 rounded-lg p-1" role="tablist">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  role="tab"
                  aria-selected={activeTab === tab.id}
                  onClick={() => onTabChange(tab.id)}
                  className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                    activeTab === tab.id
                      ? 'bg-white text-primary-600 shadow-sm'
                      : 'text-neutral-600 hover:text-neutral-900 hover:bg-white/50'
                  }`}
                >
                  <span aria-hidden="true">{tab.icon}</span>
                  <span>{tab.label}</span>
                </button>
              ))}
            </nav>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {children}
      </main>
    </div>
  )
}