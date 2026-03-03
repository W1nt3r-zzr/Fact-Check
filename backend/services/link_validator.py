"""
链接活性检测模块
解决"AI给的链接打不开"的问题
"""

import asyncio
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

import httpx
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class LinkValidationResult:
    """链接验证结果"""
    url: str
    is_accessible: bool
    status_code: Optional[int]
    response_time_ms: float
    error_message: Optional[str]
    content_type: Optional[str]
    content_length: Optional[int]
    final_url: Optional[str]  # 处理重定向后的最终URL
    timestamp: str


class LinkValidator:
    """链接活性检测器"""

    def __init__(
        self,
        timeout: float = 10.0,
        max_redirects: int = 5,
        user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    ):
        """
        初始化链接验证器

        Args:
            timeout: 请求超时时间（秒）
            max_redirects: 最大重定向次数
            user_agent: User-Agent头
        """
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.user_agent = user_agent

        # 配置HTTP客户端
        self.client_config = {
            "timeout": httpx.Timeout(timeout),
            "follow_redirects": True,
            "max_redirects": max_redirects,
            "headers": {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        }

    def _is_valid_url(self, url: str) -> bool:
        """检查URL格式是否有效"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False

    async def validate_single_link(self, url: str) -> LinkValidationResult:
        """
        验证单个链接的活性

        Args:
            url: 待验证的URL

        Returns:
            LinkValidationResult: 验证结果
        """
        timestamp = datetime.now().isoformat()

        # 预检查：URL格式
        if not self._is_valid_url(url):
            return LinkValidationResult(
                url=url,
                is_accessible=False,
                status_code=None,
                response_time_ms=0,
                error_message="URL格式无效",
                content_type=None,
                content_length=None,
                final_url=None,
                timestamp=timestamp
            )

        start_time = asyncio.get_event_loop().time()

        try:
            async with httpx.AsyncClient(**self.client_config) as client:
                logger.info(f"开始验证链接: {url}")

                # 发送HEAD请求（更轻量）
                try:
                    response = await client.head(url)
                except httpx.HTTPError:
                    # 如果HEAD请求失败，尝试GET请求
                    response = await client.get(url)

                end_time = asyncio.get_event_loop().time()
                response_time = (end_time - start_time) * 1000  # 转换为毫秒

                # 判断链接是否可访问
                is_accessible = 200 <= response.status_code < 400

                result = LinkValidationResult(
                    url=url,
                    is_accessible=is_accessible,
                    status_code=response.status_code,
                    response_time_ms=round(response_time, 2),
                    error_message=None if is_accessible else f"HTTP {response.status_code}",
                    content_type=response.headers.get("content-type"),
                    content_length=response.headers.get("content-length"),
                    final_url=str(response.url),
                    timestamp=timestamp
                )

                logger.info(
                    f"链接验证完成: {url} -> "
                    f"{'可访问' if is_accessible else '不可访问'} "
                    f"({response.status_code}, {response_time:.0f}ms)"
                )

                return result

        except httpx.TimeoutException:
            logger.warning(f"链接验证超时: {url}")
            return LinkValidationResult(
                url=url,
                is_accessible=False,
                status_code=None,
                response_time_ms=self.timeout * 1000,
                error_message=f"请求超时（>{self.timeout}秒）",
                content_type=None,
                content_length=None,
                final_url=None,
                timestamp=timestamp
            )

        except httpx.TooManyRedirects:
            logger.warning(f"链接重定向次数过多: {url}")
            return LinkValidationResult(
                url=url,
                is_accessible=False,
                status_code=None,
                response_time_ms=0,
                error_message="重定向次数过多",
                content_type=None,
                content_length=None,
                final_url=None,
                timestamp=timestamp
            )

        except httpx.ConnectError as e:
            logger.warning(f"链接连接失败: {url} - {e}")
            return LinkValidationResult(
                url=url,
                is_accessible=False,
                status_code=None,
                response_time_ms=0,
                error_message="连接失败（DNS或网络问题）",
                content_type=None,
                content_length=None,
                final_url=None,
                timestamp=timestamp
            )

        except Exception as e:
            logger.error(f"链接验证异常: {url} - {e}")
            return LinkValidationResult(
                url=url,
                is_accessible=False,
                status_code=None,
                response_time_ms=0,
                error_message=f"验证异常: {str(e)}",
                content_type=None,
                content_length=None,
                final_url=None,
                timestamp=timestamp
            )

    async def validate_multiple_links(
        self,
        urls: List[str],
        concurrent_limit: int = 5
    ) -> List[LinkValidationResult]:
        """
        并发验证多个链接

        Args:
            urls: 待验证的URL列表
            concurrent_limit: 并发限制

        Returns:
            List[LinkValidationResult]: 验证结果列表
        """
        logger.info(f"开始批量验证 {len(urls)} 个链接（并发限制: {concurrent_limit}）")

        # 创建信号量控制并发
        semaphore = asyncio.Semaphore(concurrent_limit)

        async def validate_with_semaphore(url: str):
            async with semaphore:
                return await self.validate_single_link(url)

        # 并发执行
        tasks = [validate_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks)

        # 统计结果
        accessible_count = sum(1 for r in results if r.is_accessible)
        logger.info(
            f"批量验证完成: {accessible_count}/{len(urls)} 个链接可访问 "
            f"({accessible_count/len(urls)*100:.1f}%)"
        )

        return results

    def generate_validation_report(
        self,
        results: List[LinkValidationResult]
    ) -> Dict:
        """
        生成验证报告

        Args:
            results: 验证结果列表

        Returns:
            Dict: 统计报告
        """
        total_count = len(results)
        accessible_count = sum(1 for r in results if r.is_accessible)
        inaccessible_count = total_count - accessible_count

        # 按错误类型统计
        error_stats = {}
        for result in results:
            if not result.is_accessible and result.error_message:
                error_type = result.error_message.split('(')[0].strip()
                error_stats[error_type] = error_stats.get(error_type, 0) + 1

        # 平均响应时间
        avg_response_time = sum(
            r.response_time_ms for r in results if r.is_accessible
        ) / accessible_count if accessible_count > 0 else 0

        # 重定向统计
        redirect_count = sum(
            1 for r in results
            if r.final_url and r.url != r.final_url
        )

        return {
            "total_links": total_count,
            "accessible_links": accessible_count,
            "inaccessible_links": inaccessible_count,
            "accessibility_rate": f"{accessible_count/total_count*100:.1f}%" if total_count > 0 else "0%",
            "average_response_time_ms": round(avg_response_time, 2),
            "redirected_links": redirect_count,
            "error_breakdown": error_stats,
            "timestamp": datetime.now().isoformat()
        }


# 使用示例和测试
async def main():
    """测试链接验证功能"""
    validator = LinkValidator(timeout=5.0)

    # 测试URL列表
    test_urls = [
        "https://www.baidu.com",  # 正常链接
        "https://www.gov.cn",  # 政府网站
        "https://this-domain-does-not-exist-12345.com",  # 不存在的域名
        "https://httpbin.org/status/404",  # 404页面
        "https://httpbin.org/delay/10",  # 超时页面
    ]

    results = await validator.validate_multiple_links(test_urls, concurrent_limit=3)

    # 打印结果
    for result in results:
        status = "✅" if result.is_accessible else "❌"
        print(f"{status} {result.url}")
        if not result.is_accessible:
            print(f"   错误: {result.error_message}")
        else:
            print(f"   状态码: {result.status_code}, 响应时间: {result.response_time_ms}ms")

    # 生成报告
    report = validator.generate_validation_report(results)
    print("\n=== 验证报告 ===")
    print(f"总计: {report['total_links']} 个链接")
    print(f"可访问: {report['accessible_links']} 个")
    print(f"不可访问: {report['inaccessible_links']} 个")
    print(f"可访问率: {report['accessibility_rate']}")
    print(f"平均响应时间: {report['average_response_time_ms']} ms")


if __name__ == "__main__":
    asyncio.run(main())
