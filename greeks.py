import math

def norm_cdf(x):
    """
    표준정규분포의 누적분포함수 (Cumulative Distribution Function, CDF)
    math.erf를 사용하여 의존성 없이 계산
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def norm_pdf(x):
    """
    표준정규분포의 확률밀도함수 (Probability Density Function, PDF)
    """
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x**2)

def calculate_greeks(flag, S, K, T, r, sigma):
    """
    블랙-숄즈 모델을 이용한 옵션 그릭스 계산 (Pure Python)
    
    Parameters:
      flag (str) : 'c' 또는 'call' (콜옵션), 'p' 또는 'put' (풋옵션)
      S (float)  : 기초자산 현재가 (Underlying Spot Price)
      K (float)  : 행사가격 (Strike Price)
      T (float)  : 잔존만기 (Years to Expiry, e.g. 30일 = 30/365)
      r (float)  : 무위험 이자율 (Risk-free Rate, e.g. 4.5% = 0.045)
      sigma (float): 내재변동성 (Implied Volatility, e.g. 20% = 0.20)
      
    Returns:
      dict: {'price': 옵션이론가, 'delta': 델타, 'gamma': 감마, 'vega': 베가(1% IV변동 기준), 'theta': 세타(1일 기준)}
    """
    # 예외 상황 및 극단적인 입력값 처리
    if T <= 0:
        return {'price': 0.0, 'delta': 0.0, 'gamma': 0.0, 'vega': 0.0, 'theta': 0.0}
    if sigma <= 0:
        sigma = 0.0001  # 0 나누기 방지
        
    is_call = flag.lower() in ('c', 'call')
    
    # 블랙-숄즈 파라미터 d1, d2 계산
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
    except (ValueError, ZeroDivisionError):
        return {'price': 0.0, 'delta': 0.0, 'gamma': 0.0, 'vega': 0.0, 'theta': 0.0}

    # 누적 분포 함수 값 및 PDF 값
    cdf_d1 = norm_cdf(d1)
    cdf_d2 = norm_cdf(d2)
    pdf_d1 = norm_pdf(d1)
    
    # 1. 옵션 이론가 계산
    if is_call:
        price = S * cdf_d1 - K * math.exp(-r * T) * cdf_d2
    else:
        price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
        
    # 2. 델타 (Delta)
    delta = cdf_d1 if is_call else cdf_d1 - 1.0
    
    # 3. 감마 (Gamma)
    gamma = pdf_d1 / (S * sigma * math.sqrt(T))
    
    # 4. 베가 (Vega)
    # 수학적인 Vega는 S * sqrt(T) * pdf(d1) 이지만, 
    # 실무 대시보드 시각화에서는 보통 'IV 1%p 변동 시 옵션 가치 변동'을 나타내므로 0.01을 곱해줍니다.
    vega = S * math.sqrt(T) * pdf_d1 * 0.01
    
    # 5. 세타 (Theta)
    # 연 단위 세타 공식에서 하루 단위 세타로 표기하기 위해 365로 나누어 줍니다. (Day Theta)
    term1 = -(S * pdf_d1 * sigma) / (2.0 * math.sqrt(T))
    if is_call:
        term2 = -r * K * math.exp(-r * T) * cdf_d2
        theta_annual = term1 + term2
    else:
        term2 = r * K * math.exp(-r * T) * norm_cdf(-d2)
        theta_annual = term1 + term2
        
    theta_daily = theta_annual / 365.0
    
    # 가독성을 고려한 반올림 처리
    return {
        'price': round(price, 4),
        'delta': round(delta, 4),
        'gamma': round(gamma, 6),
        'vega': round(vega, 4),
        'theta': round(theta_daily, 4)
    }

# 모듈 정상 동작 테스트용 코드
if __name__ == "__main__":
    # 테스트 입력값: Spot=100, Strike=100, T=30일(30/365), r=4.5%(0.045), IV=25%(0.25)
    test_result_call = calculate_greeks('call', 100, 100, 30/365, 0.045, 0.25)
    test_result_put = calculate_greeks('put', 100, 100, 30/365, 0.045, 0.25)
    print("Call Greeks Test:", test_result_call)
    print("Put Greeks Test:", test_result_put)
