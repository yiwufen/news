import { useEffect, useState, useCallback } from 'react'
import { Table, Drawer, Descriptions, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchEventClusters, fetchEventCluster } from '../api/event-clusters'
import type { ClusterSummary } from '../api/types'

const conflictColors: Record<string, string> = {
  none: 'green',
  possible: 'orange',
  confirmed: 'red',
}

const columns: ColumnsType<ClusterSummary> = [
  { title: 'Title', dataIndex: 'title', ellipsis: true },
  {
    title: 'Type',
    dataIndex: 'cluster_type',
    width: 160,
    ellipsis: true,
  },
  {
    title: 'Members',
    dataIndex: 'member_count',
    width: 90,
    align: 'center',
  },
  {
    title: 'Sources',
    dataIndex: 'source_count',
    width: 90,
    align: 'center',
  },
  {
    title: 'Conflict',
    dataIndex: 'conflict_status',
    width: 90,
    render: (v: string) => <Tag color={conflictColors[v] || 'default'}>{v}</Tag>,
  },
  {
    title: 'Updated',
    dataIndex: 'updated_at',
    width: 180,
    render: (v: string) => new Date(v).toLocaleString(),
  },
]

export default function EventClusters() {
  const [data, setData] = useState<ClusterSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchEventClusters(page, pageSize)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize])

  useEffect(() => { loadData() }, [loadData])

  const handleRowClick = async (record: ClusterSummary) => {
    const d = await fetchEventCluster(record.cluster_id)
    setDetail(d)
    setDrawerOpen(true)
  }

  return (
    <div>
      <Table<ClusterSummary>
        columns={columns}
        dataSource={data}
        rowKey="cluster_id"
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
        title="Event Cluster Detail"
        width={720}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {detail && (
          <Descriptions column={1} bordered size="small">
            {Object.entries(detail).map(([key, value]) => (
              <Descriptions.Item key={key} label={key}>
                {Array.isArray(value)
                  ? value.length > 0
                    ? JSON.stringify(value, null, 2)
                    : '[]'
                  : typeof value === 'object' && value !== null
                    ? JSON.stringify(value, null, 2)
                    : String(value ?? '')}
              </Descriptions.Item>
            ))}
          </Descriptions>
        )}
      </Drawer>
    </div>
  )
}
