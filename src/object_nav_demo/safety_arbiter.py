from __future__ import annotations

from .models import SafetyDecision, SafetyInputs


class SafetyArbiter:
    def evaluate(self, inputs: SafetyInputs) -> SafetyDecision:
        checks = (
            (inputs.estop_clear is True, "安全状态未知或急停未释放"),
            (inputs.odometry_ok, "短时里程计不可用"),
            (inputs.navigation_healthy, "导航接口故障"),
            (inputs.camera_fresh, "相机数据超时"),
            (inputs.path_clear, "局部路径受阻"),
        )
        for passed, reason in checks:
            if not passed:
                return SafetyDecision(False, reason)
        return SafetyDecision(True, "安全门槛通过")
