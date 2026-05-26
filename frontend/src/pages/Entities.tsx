import { useEffect, useState, useCallback } from 'react'
import { Table, Input, Drawer, Tabs, Descriptions, Tag, Space, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { fetchEntities, fetchEntity, fetchEntityRelatedKUs, fetchEntityRelatedClusters } from '../api/entities'
import type { EntitySummary, KUSummary, ClusterSummary } from '../api/types'

const columns: ColumnsType<EntitySummary> = [
  { title: 'Name', dataIndex: 'canonical_name', width: 300 },
  {
    title: 'Type',
    dataIndex: 'entity_type',
    width: 120,
    render: (v: string) => <Tag color="blue">{v || 'Unknown'}</Tag>,
  },
  {
    title: 'Updated',
    dataIndex: 'updated_at',
    width: 200,
    render: (v: string) => new Date(v).toLocaleString(),
  },
]

const kuColumns: ColumnsType<KUSummary> = [
  { title: 'Type', dataIndex: 'unit_type', width: 160, ellipsis: true },
  { title: 'Summary', dataIndex: 'summary', ellipsis: true },
  {
    title: 'Published',
    dataIndex: 'published_at',
    width: 160,
    render: (v: string) => new Date(v).toLocaleString(),
  },
]

const clusterColumns: ColumnsType<ClusterSummary> = [
  { title: 'Title', dataIndex: 'title', ellipsis: true },
  { title: 'Type', dataIndex: 'cluster_type', width: 160, ellipsis: true },
  {
    title: 'Members',
    dataIndex: 'member_count',
    width: 80,
    align: 'center',
  },
]

export default function Entities() {
  const [data, setData] = useState<EntitySummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const navigate = useNavigate()

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchEntities(page, pageSize, search)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, search])

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => {
    const autoOpen = sessionStorage.getItem('autoOpenEntity')
    if (autoOpen) {
      sessionStorage.removeItem('autoOpenEntity')
      fetchEntity(autoOpen).then((d) => { setDetail(d); setDetailId(autoOpen); setDrawerOpen(true) }).catch(() => {})
    }
  }, [])

  const handleRowClick = async (record: EntitySummary) => {
    const d = await fetchEntity(record.entity_id)
    setDetail(d)
    setDetailId(record.entity_id)
    setDrawerOpen(true)
  }

  const openKU = (kuId: string) => {
    setDrawerOpen(false)
    sessionStorage.setItem('autoOpenKU', kuId)
    navigate('/knowledge-units')
  }

  const openCluster = (clusterId: string) => {
    setDrawerOpen(false)
    sessionStorage.setItem('autoOpenCluster', clusterId)
    navigate('/event-clusters')
  }

  const displayValue = (value: unknown): string => {
    if (Array.isArray(value)) return value.length > 0 ? JSON.stringify(value) : '[]'
    if (typeof value === 'object' && value !== null) return JSON.stringify(value, null, 2)
    return String(value ?? '')
  }

  const basicInfoFields = detail
    ? Object.entries(detail).filter(([, v]) => typeof v !== 'object' || v === null || Array.isArray(v))
    : []

  const tabs = detail ? [
    {
      key: 'info',
      label: 'Basic Info',
      children: (
        <Descriptions column={1} bordered size="small">
          {basicInfoFields.map(([key, value]) => (
            <Descriptions.Item key={key} label={key}>
              {displayValue(value)}
            </Descriptions.Item>
          ))}
        </Descriptions>
      ),
    },
    {
      key: 'kus',
      label: 'Knowledge Units',
      children: (
        <RelatedKUsTable entityId={detailId!} onKUClick={openKU} />
      ),
    },
    {
      key: 'clusters',
      label: 'Event Clusters',
      children: (
        <RelatedClustersTable entityId={detailId!} onClusterClick={openCluster} />
      ),
    },
  ] : []

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="Search entities..."
          allowClear
          onSearch={setSearch}
          style={{ width: 300 }}
        />
      </Space>

      <Table<EntitySummary>
        columns={columns}
        dataSource={data}
        rowKey="entity_id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `Total ${t}`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        onRow={(record) => ({ onClick: () => handleRowClick(record), style: { cursor: 'pointer' } })}
        size="small"
      />

      <Drawer
        title={detail?.canonical_name as string || 'Entity Detail'}
        width={720}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {detail && <Tabs items={tabs} />}
      </Drawer>
    </div>
  )
}

function RelatedKUsTable({ entityId, onKUClick }: { entityId: string; onKUClick: (id: string) => void }) {
  const [data, setData] = useState<KUSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchEntityRelatedKUs(entityId, page, 10)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [entityId, page])

  useEffect(() => { load() }, [load])

  return (
    <Table<KUSummary>
      columns={kuColumns}
      dataSource={data}
      rowKey="ku_id"
      loading={loading}
      size="small"
      pagination={{
        current: page,
        pageSize: 10,
        total,
        size: 'small',
        showTotal: (t) => <Typography.Text type="secondary">Total {t}</Typography.Text>,
        onChange: (p) => setPage(p),
      }}
      onRow={(r) => ({ onClick: () => onKUClick(r.ku_id), style: { cursor: 'pointer' } })}
    />
  )
}

function RelatedClustersTable({ entityId, onClusterClick }: { entityId: string; onClusterClick: (id: string) => void }) {
  const [data, setData] = useState<ClusterSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchEntityRelatedClusters(entityId, page, 10)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [entityId, page])

  useEffect(() => { load() }, [load])

  return (
    <Table<ClusterSummary>
      columns={clusterColumns}
      dataSource={data}
      rowKey="cluster_id"
      loading={loading}
      size="small"
      pagination={{
        current: page,
        pageSize: 10,
        total,
        size: 'small',
        showTotal: (t) => <Typography.Text type="secondary">Total {t}</Typography.Text>,
        onChange: (p) => setPage(p),
      }}
      onRow={(r) => ({ onClick: () => onClusterClick(r.cluster_id), style: { cursor: 'pointer' } })}
    />
  )
}
