import { Typography, Steps, Card } from 'antd'

const { Title, Paragraph, Text } = Typography

export default function Neo4jGuide() {
  return (
    <div>
      <Title level={4}>Neo4j Graph Browser</Title>
      <Paragraph>
        Neo4j Browser 需要通过 SSH 隧道访问（bolt 协议不能通过 HTTP 反代）。
      </Paragraph>

      <Card style={{ maxWidth: 720, marginTop: 16 }}>
        <Steps direction="vertical" size="small" current={-1} items={[
          {
            title: '获取 Neo4j 容器 IP',
            description: (
              <Text code>{'ssh baidu "docker inspect -f \'{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}\' knowledge-neo4j"'}</Text>
            ),
          },
          {
            title: '建立 SSH 隧道',
            description: (
              <Text code>{'ssh -L 17474:<容器IP>:7474 -L 17687:<容器IP>:7687 baidu'}</Text>
            ),
          },
          {
            title: '打开 Neo4j Browser',
            description: (
              <div>
                浏览器访问 <Text code>http://localhost:17474</Text>
                <br />
                连接地址：<Text code>bolt://localhost:17687</Text>
              </div>
            ),
          },
        ]} />
      </Card>
    </div>
  )
}
