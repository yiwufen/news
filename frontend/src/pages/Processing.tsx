import { useEffect, useState, useCallback } from 'react'
import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchProcessingLog } from '../api/processing'
import type { ProcessingLogEntry } from '../api/types'

const statusColors: Record<string, string> = {
  processed: 'green',
  failed: 'red',
  pending: 'orange',
  processing: 'blue',
}

const columns: ColumnsType<ProcessingLogEntry> = [
  { title: 'Doc ID', dataIndex: 'doc_id', width: 200, ellipsis: true },
  {
    title: 'Status',
    dataIndex: 'status',
    width: 100,
    render: (v: string) => <Tag color={statusColors[v] || 'default'}>{v}</Tag>,
  },
  {
    title: 'KUs',
    dataIndex: 'knowledge_units_count',
    width: 80,
    align: 'center',
  },
  {
    title: 'Entities',
    dataIndex: 'entities_count',
    width: 80,
    align: 'center',
  },
  {
    title: 'Clusters',
    dataIndex: 'clusters_count',
    width: 80,
    align: 'center',
  },
  {
    title: 'Error',
    dataIndex: 'error_message',
    ellipsis: true,
    render: (v: string | null) => v || '-',
  },
  {
    title: 'Updated',
    dataIndex: 'updated_at',
    width: 180,
    render: (v: string) => new Date(v).toLocaleString(),
  },
]

export default function Processing() {
  const [data, setData] = useState<ProcessingLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchProcessingLog(page, pageSize)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize])

  useEffect(() => { loadData() }, [loadData])

  return (
    <div>
      <Table<ProcessingLogEntry>
        columns={columns}
        dataSource={data}
        rowKey="doc_id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `Total ${t}`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        size="small"
      />
    </div>
  )
}
