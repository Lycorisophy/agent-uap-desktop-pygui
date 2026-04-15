"""
熵值分析模块
计算时间序列的各种熵值指标
"""

from typing import List, Tuple
from dataclasses import dataclass
from enum import Enum
import math


class EntropyType(Enum):
    PERMUTATION = "permutation_entropy"
    SAMPLE = "sample_entropy"
    SHANNON = "shannon_entropy"


@dataclass
class EntropyResult:
    entropy_type: EntropyType
    value: float
    normalized_value: float
    interpretation: str
    details: dict


class PermutationEntropy:
    """排列熵计算"""
    
    def __init__(self, embedding_dimension: int = 3, delay: int = 1):
        self.embedding_dimension = embedding_dimension
        self.delay = delay
    
    def calculate(self, data: List[float]) -> float:
        if len(data) < self.embedding_dimension * self.delay + 1:
            return 0.0
        
        n = len(data)
        d = self.embedding_dimension
        
        patterns = []
        for i in range(0, n - d * self.delay, self.delay):
            pattern = tuple(data[i + j * self.delay] for j in range(d))
            sorted_indices = sorted(range(d), key=lambda k: pattern[k])
            symbol = tuple(sorted_indices)
            patterns.append(symbol)
        
        from collections import Counter
        counts = Counter(patterns)
        total = len(patterns)
        
        entropy = 0.0
        for count in counts.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)
        
        return entropy
    
    def normalize(self, entropy: float) -> float:
        max_entropy = math.log2(math.factorial(self.embedding_dimension))
        return entropy / max_entropy if max_entropy > 0 else 0.0


class SampleEntropy:
    """样本熵计算"""
    
    def __init__(self, embedding_dimension: int = 2, tolerance: float = 0.2):
        self.embedding_dimension = embedding_dimension
        self.tolerance = tolerance
    
    def calculate(self, data: List[float]) -> float:
        if len(data) < self.embedding_dimension * 2 + 1:
            return 0.0
        
        n = len(data)
        d = self.embedding_dimension
        r = self._get_tolerance(data)
        
        def count_matches(dim: int) -> int:
            count = 0
            for i in range(n - dim):
                for j in range(i + 1, n - dim):
                    match = True
                    for k in range(dim):
                        if abs(data[i + k] - data[j + k]) > r:
                            match = False
                            break
                    if match:
                        count += 1
            return count
        
        a = count_matches(d + 1)
        b = count_matches(d)
        
        if b == 0 or a == 0:
            return 0.0
        
        return -math.log(a / b)
    
    def _get_tolerance(self, data: List[float]) -> float:
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        std = math.sqrt(variance)
        return self.tolerance * std


class EntropyAnalyzer:
    """综合熵值分析器"""
    
    def __init__(self):
        self.perm_entropy = PermutationEntropy()
        self.sample_entropy = SampleEntropy()
    
    def analyze(self, data: List[float], dimensions: List[int] = [3, 4, 5]) -> List[EntropyResult]:
        results = []
        
        for d in dimensions:
            pe = PermutationEntropy(embedding_dimension=d)
            pe_value = pe.calculate(data)
            results.append(EntropyResult(
                entropy_type=EntropyType.PERMUTATION,
                value=pe_value,
                normalized_value=pe.normalize(pe_value),
                interpretation=self._interpret_permutation_entropy(pe.normalize(pe_value)),
                details={'embedding_dimension': d}
            ))
        
        se = SampleEntropy()
        se_value = se.calculate(data)
        results.append(EntropyResult(
            entropy_type=EntropyType.SAMPLE,
            value=se_value,
            normalized_value=min(se_value / 2, 1.0),
            interpretation=self._interpret_sample_entropy(se_value),
            details={'embedding_dimension': 2}
        ))
        
        return results
    
    def _interpret_permutation_entropy(self, normalized: float) -> str:
        if normalized < 0.3:
            return "高度规律，系统可预测性强"
        elif normalized < 0.5:
            return "中等规律，存在一定复杂度"
        elif normalized < 0.7:
            return "较高复杂度"
        else:
            return "高度复杂/随机"
    
    def _interpret_sample_entropy(self, value: float) -> str:
        if value < 0.5:
            return "序列规律性强"
        elif value < 1.0:
            return "中等自相似性"
        elif value < 2.0:
            return "较低自相似性"
        else:
            return "序列复杂"
    
    def get_summary(self, results: List[EntropyResult]) -> dict:
        if not results:
            return {'status': 'no_data'}
        
        avg_entropy = sum(r.normalized_value for r in results) / len(results)
        predictability = 1.0 - avg_entropy
        
        return {
            'average_entropy': avg_entropy,
            'predictability': predictability,
            'interpretation': self._interpret_predictability(predictability),
            'recommendations': self._get_recommendations(results)
        }
    
    def _interpret_predictability(self, p: float) -> str:
        if p > 0.7:
            return "系统高度可预测"
        elif p > 0.4:
            return "系统中等可预测"
        elif p > 0.2:
            return "系统可预测性较低"
        else:
            return "系统高度不可预测"
    
    def _get_recommendations(self, results: List[EntropyResult]) -> list:
        recommendations = []
        perm_entropy = next((r for r in results if r.entropy_type == EntropyType.PERMUTATION), None)
        if perm_entropy and perm_entropy.normalized_value > 0.7:
            recommendations.append("检测到高复杂度，考虑使用神经网络方法")
        if not recommendations:
            recommendations.append("系统状态稳定，当前预测方法适用")
        return recommendations
