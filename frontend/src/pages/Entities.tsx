import { useEffect, useState, useCallback } from 'react'
import { Table, Input, Drawer, Descriptions, Tag, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchEntities, fetchEntity } from '../api/entities'
import type { EntitySummary } from '../api/types'

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

export default function Entities() {
  const [data, setData] = useState<EntitySummary[]>([])
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
      const res = await fetchEntities(page, pageSize, search)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, search])

  useEffect(() => { loadData() }, [loadData])

  const handleRowClick = async (record: EntitySummary) => {
    const d = await fetchEntity(record.entity_id)
    setDetail(d)
    setDrawerOpen(true)
  }

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
        width={640}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {detail && (
          <Descriptions column={1} bordered size="small">
            {Object.entries(detail).map(([key, value]) => (
              <Descriptions.Item key={key} label={key}>
                {Array.isArray(value)
                  ? value.join(', ')
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
