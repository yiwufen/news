import { useEffect, useState, useCallback } from 'react'
import { Table, Input, Drawer, Descriptions, Tag, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchKnowledgeUnits, fetchKnowledgeUnit } from '../api/knowledge-units'
import type { KUSummary } from '../api/types'

const conflictColors: Record<string, string> = {
  none: 'green',
  possible: 'orange',
  confirmed: 'red',
}

const columns: ColumnsType<KUSummary> = [
  { title: 'Type', dataIndex: 'unit_type', width: 160, ellipsis: true },
  {
    title: 'Summary',
    dataIndex: 'summary',
    ellipsis: true,
  },
  {
    title: 'Kind',
    dataIndex: 'unit_kind',
    width: 80,
    render: (v: string) => <Tag>{v}</Tag>,
  },
  {
    title: 'Published',
    dataIndex: 'published_at',
    width: 180,
    render: (v: string) => new Date(v).toLocaleString(),
  },
  {
    title: 'Conflict',
    dataIndex: 'conflict_status',
    width: 90,
    render: (v: string) => <Tag color={conflictColors[v] || 'default'}>{v}</Tag>,
  },
]

export default function KnowledgeUnits() {
  const [data, setData] = useState<KUSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchKnowledgeUnits(page, pageSize, search)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, search])

  useEffect(() => { loadData() }, [loadData])

  const handleRowClick = async (record: KUSummary) => {
    const d = await fetchKnowledgeUnit(record.ku_id)
    setDetail(d)
    setDrawerOpen(true)
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="Search knowledge units..."
          allowClear
          onSearch={setSearch}
          style={{ width: 300 }}
        />
      </Space>

      <Table<KUSummary>
        columns={columns}
        dataSource={data}
        rowKey="ku_id"
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
        title="Knowledge Unit Detail"
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
