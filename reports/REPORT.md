# Lab 25B — Report

**Họ tên / nhóm:** Dương Thị Ngân — **MSV:** 2A202602808  
**Commit mã nguồn:** `9bc6a9a96265dd4440d6ce4134c7417bd0e2302f`  
**Điểm tự động (`make grade`):** **84/88 điểm công khai**; 4 điểm SLO còn lại do giảng viên chấm trên dữ liệu ẩn.

Mọi số liệu dưới đây được lấy từ `reports/gameday/*.json`, `reports/workflows.json`, `reports/slo.json`, `reports/cache/*.json` và `reports/experiments.json`.

## 1. Kết quả Game Day — naive so với resilient

| Băng | Client | availability | p95 (s) | amplification | retry_ratio | cost/turn | recovery (s) | PASS? |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| G1 | naive | 0.7194 | 7.157 | 7.738 | 6.738 | 2.163 | 4 | Không |
| G1 | resilient | 1.0000 | 4.780 | 1.063 | 0.001 | 2.104 | 0 | Có |
| G2 | naive | 0.4560 | 15.034 | 9.904 | 8.904 | 4.627 | 155 | Không |
| G2 | resilient | 1.0000 | 10.362 | 1.036 | 0.005 | 2.108 | 0 | Có |
| G3 | naive | 1.0000 | 4.768 | 1.164 | 0.164 | 2.328 | 0 | Không |
| G3 | resilient | 1.0000 | 4.668 | 1.059 | 0.030 | 2.143 | 0 | Có |
| G4 | naive | 1.0000 | 13.764 | 1.004 | 0.004 | 2.008 | 0 | Không |
| G4 | resilient | 1.0000 | 5.626 | 1.014 | 0.002 | 2.072 | 0 | Có |
| G5 | naive | 0.3699 | 5.359 | 17.030 | 16.030 | 2.124 | — | Không |
| G5 | resilient | 0.8179 | 5.477 | 1.003 | 0.002 | 2.504 | — | Có |
| G6 | naive | 0.5170 | 4.836 | 12.344 | 11.344 | 2.009 | 0 | Không |
| G6 | resilient | 1.0000 | 6.025 | 1.056 | 0.019 | 2.188 | 0 | Có |

Resilient client đạt 6/6 băng ở seed 25. Kiểm tra bổ sung bằng seed 1, 7 và 42 cũng đều đạt 6/6; cache C1 cũng PASS ở cả ba seed.

## 2. Cấu hình client và lý do

| Tham số | Giá trị | Lý do dựa trên số liệu |
|---|---:|---|
| `attempt_timeout_s` | 8.0 | Đủ cho G4 chậm thêm 5 giây nhưng p95 vẫn 5.626 giây. Khi tăng lên 30 giây, G6 giảm availability từ 1.0000 xuống 0.9488 và có 109 lần `deadline` give-up. |
| `max_attempts_per_provider` | 2 | Cho phép đúng một retry cùng provider. G2 chỉ amplification 1.036; thí nghiệm 5 attempt và tắt budget làm amplification tăng lên 1.591. |
| `backoff_base_s / cap_s` | 0.25 / 4.0 | Full jitter đủ phân tán retry và tôn trọng `retry-after`; G1 có 0 vi phạm, availability 1.0000, amplification 1.063. |
| `retry_budget_ratio` | 0.10 | Khi breaker cố ý bị vô hiệu, budget giữ G2 ở retry ratio 0.058 và amplification 1.383; tắt budget làm hai số tăng lên 0.382 và 1.591. |
| `breaker.window_size / min_calls` | 20 / 10 | Cửa sổ đủ ngắn để phản ứng nhưng cần 10 kết quả để tránh trip vì nhiễu. G2 phục hồi 0 giây; G3 giữ retry ratio 0.030. |
| `breaker.failure_rate_threshold` | 0.50 | Trip khi ít nhất nửa cửa sổ hỏng; đủ nhanh cho G2/G6 nhưng không mở vì lỗi 400 hay 429 của tenant. |
| `breaker.slow_call_s` | 5.0 | Bắt brown-slow trước timeout. G4 p95 giảm từ 13.764 xuống 5.626 giây dù provider vẫn trả thành công. |
| `breaker.open_duration_s` | 10.0 | Giảm tải đủ lâu nhưng vẫn probe sớm; G2 quay lại primary với recovery 0 giây. |
| `breaker.half_open_max_probes` | 2 | Chỉ hai probe đồng thời, tránh thundering herd; cả G2 và G6 đều availability 1.0000. |

Luồng quyết định của `on_error`:

| Loại lỗi | Breaker | Retry cùng provider | Failover / kết thúc |
|---|---|---|---|
| `CLIENT_ERROR` | Release permit, không ghi lỗi sức khỏe | Không | `GiveUp("client_error")`; không gửi request sai sang provider khác |
| `QUOTA_EXHAUSTED` | Release permit | Không | Cooldown 300 giây rồi failover ngay |
| `RATE_LIMITED` | Release permit | Không | Cooldown đúng `retry_after`, failover ngay; chỉ chờ tối đa 5 giây nếu mọi provider đều bận |
| `OVERLOADED`, `SERVER_ERROR`, `TIMEOUT` | Ghi failure; breaker có thể OPEN | Full jitter nếu chưa quá 2 attempt, budget còn token và còn deadline | Nếu không retry được thì chuyển provider tiếp theo |
| Thành công | Ghi latency; success chậm ≥ 5 giây vẫn là tín hiệu xấu | — | Kết thúc; HALF-OPEN đóng sau 2 probe tốt |

## 3. Ba thí nghiệm

1. **Retry budget là lớp phòng thủ cuối.** Em cố ý đặt `breaker.min_calls=1_000_000_000` và `max_attempts_per_provider=5`. Với budget, G2 đạt availability 0.9987, amplification 1.383, retry ratio 0.058, recovery 0 giây; khi tắt budget, availability giảm còn 0.9725, amplification tăng 1.591, retry ratio tăng 0.382 và recovery thành 22 giây. Ở G3, budget giảm retry ratio từ 0.160 xuống 0.068. Breaker khỏe chặn theo từng provider và budget chặn tổng lượng retry, nên vẫn cần cả hai để chống cấu hình sai, race và lỗi chưa đủ mẫu để breaker trip.

2. **`attempt_timeout_s=30`.** Trên G6, availability giảm từ 1.0000 xuống 0.9488; có 109 lượt bỏ cuộc vì `deadline` và 13 lượt `no_provider_available`, dù p95 của các lượt sống sót chỉ 5.304 giây. Đây là survivorship bias: các lượt treo 30 giây thất bại không nằm trong p95 thành công. G4 gần như không đổi (availability 1.0000, p95 5.683 giây) vì provider vẫn trả trước deadline. Timeout nên lấy từ p99 khỏe mạnh cộng biên mạng, nhưng phải chừa đủ thời gian trong deadline 30 giây cho ít nhất một lần failover.

3. **Bỏ lọc tool calling.** G6 tạo 252 route không tương thích tới `gamma-mini`, 252 lượt `incompatible_model_output`, làm availability giảm từ 1.0000 xuống 0.8943. Nói theo ngôn ngữ sản phẩm: hệ thống đã chuyển yêu cầu cần thao tác đơn hàng sang model chỉ biết chat, nên 252 khách nhận luồng không thể hoàn thành dù model đó vẫn “đang online”.

## 4. Workflow hoàn tiền exactly-once

| Executor | completion | crashes | duplicate refunds | duplicate emails | lost refunds | overpaid | wasted LLM / crash |
|---|---:|---:|---:|---:|---:|---:|---:|
| naive | 1.000 | 81 | 128 | 81 | 0 | 1,496,700 cents | 1.123 |
| yours | 1.000 | 66 | 0 | 0 | 0 | 0 cents | 0.303 |

Idempotency key ổn định bảo vệ side effect khi response bị mất hoặc worker chết sau commit, nhưng không tránh việc gọi lại các bước đọc/LLM và không cho worker mới biết bước nào đã hoàn tất. Checkpoint giúp resume, nhưng nếu chỉ có checkpoint thì crash sau khi payment đã chạy và trước khi checkpoint được ghi vẫn có thể trả tiền lần hai. Vì vậy cần cả hai: chạy side effect với key ổn định, sau khi nhận kết quả mới ghi checkpoint. Ghi checkpoint trước payment có thể khiến lần resume bỏ qua một khoản hoàn tiền chưa từng được thực hiện, tạo `lost_refund`.

## 5. Alerting và error budget

| Sự cố | Mong đợi | Naive alerter | Burn-rate alerter | Độ trễ burn-rate (phút) |
|---|---|---|---|---:|
| `checkout_bug` | page | page sau 1 phút | page | 27 |
| `provider_outage` | page | page ngay | page | 4 |
| `deploy_blip` | none | page sai | không alert | — |
| `slow_leak` | ticket | bỏ sót | ticket | 1337 |
| `degraded_evening` | page | page sau 214 phút | page | 291 |
| `night_spike` | none | page sai | không alert | — |
| `small_bump` | none | page sai | không alert | — |

Trong 25,901,755 request, có 55,618 lỗi trên ngân sách cho phép 129,508.8: availability 0.997853, đã tiêu **42.95%**, còn **57.05%**, nên **không đóng băng release**. `small_bump` kéo dài 20 phút ở 12% lỗi nhưng không đồng thời vượt cả cửa sổ dài và ngắn của luật burn-rate; đánh thức on-call lúc 11 giờ trưa cho một bump tự hồi phục sẽ tạo alert fatigue mà không bảo vệ đáng kể error budget.

## 6. Postmortem — G2 với naive client (blameless)

![G2 overload storm](G2_overload_storm.png)

**Tóm tắt.** Từ t=120 đến t=300, `alpha` mất 75% GPU; client naive phản ứng bằng ba tầng retry và biến suy giảm công suất thành retry storm. Trong 2,362 lượt user, chỉ 1,077 thành công: availability 45.60%, 1,285 lượt thất bại, amplification 9.904 và p95 15.034 giây. Provider hồi phục ở t=300 nhưng hệ thống cần thêm 155 giây mới phục hồi vì hàng đợi cũ và retry tiếp tục tự duy trì tải.

**Ảnh hưởng.** Tác động kéo dài khoảng 335 giây, từ lúc giảm công suất t=120 đến khi recovery hoàn tất khoảng t=455. Với tốc độ quan sát 2,362 lượt/600 giây, 30 ngày tương đương khoảng 10,203,840 lượt và ngân sách lỗi 0.5% là 51,019 lượt; 1,285 lỗi của G2 tiêu khoảng **2.52% ngân sách lỗi tháng**.

**Timeline từ CSV:**

| t | Sự kiện | Bằng chứng theo giây (`calls_ok/calls_done`, attempts alpha) |
|---:|---|---|
| 119 | Trước sự cố, hệ thống khỏe | 7/7 call thành công, 9 attempt alpha |
| 120 | Alpha mất 75% GPU | 7/7 call thành công, 5 attempt; hàng đợi bắt đầu tích tụ |
| 150 | Retry storm hình thành | 0/3 call thành công, **163** attempt alpha/giây |
| 240 | Sự cố tiếp diễn | 0/2 call thành công, 105 attempt alpha/giây |
| 299 | Ngay trước restore | 0/1 call thành công, 136 attempt alpha/giây |
| 300 | GPU được khôi phục | vẫn 0/5 call thành công, 115 attempt alpha/giây |
| 360 | Metastable tail | 0/1 call thành công, 50 attempt alpha/giây dù provider đã khỏe 60 giây |
| 420 | Chưa hồi phục hoàn toàn | 0/2 call thành công, 53 attempt alpha/giây |
| 455 | Recovery window đạt lại ngưỡng | 4/5 call thành công, attempts giảm còn 13/giây |
| 480 | Bình thường hóa | 11/11 call thành công, 8 attempt alpha/giây |

**Trigger và root cause.** Trigger là việc `alpha` mất 75% năng lực GPU trong 180 giây. Root cause nằm ở thiết kế hệ thống: app × gateway × SDK cho phép tối đa 36 attempt/call, delay cố định, không retry budget, không breaker và không fallback. Request mà client đã bỏ vẫn tiếp tục chiếm server; retry lại đổ thêm request vào hàng đợi, đẩy tải cao hơn năng lực xử lý. Sau t=300, GPU hồi phục nhưng hàng đợi đầy cộng với retry mới vẫn giữ tải trên công suất, tạo vòng lặp metastable không tự dừng ngay.

**Điều giúp / làm tệ hơn.** Provider cuối cùng khôi phục đủ GPU và traffic đầu vào không tăng thêm nên backlog có thể rút dần. Ngược lại, retry đồng bộ, timeout rồi bỏ request đang chạy, không giới hạn amplification và chỉ dùng một provider khiến backlog kéo dài thêm 155 giây. Resilient client phá vòng lặp này: G2 đạt availability 1.0000, amplification 1.036 và recovery 0 giây.

**Action items:**

| # | Hành động | Loại | Owner | Cách kiểm chứng |
|---|---|---|---|---|
| 1 | Chỉ giữ một tầng retry, full jitter và retry budget 10% | prevent | Agent Platform | CI chạy G2 với amplification ≤ 1.6 và retry ratio được ghi vào dashboard |
| 2 | Triển khai sliding-window breaker gồm slow-call và HALF-OPEN tối đa 2 probe | mitigate | Runtime/SRE | Chaos test G2 yêu cầu recovery ≤ 30 giây; unit test xác nhận stale permit và probe limit |
| 3 | Dashboard attempts/logical-call, queue wait, breaker state; page khi amplification > 1.6 trong 5 phút | detect | Observability | Drill tạo retry storm phải phát hiện trong ≤ 5 phút và liên kết đúng incident |
| 4 | Capability-aware fallback sang `alpha-eu`/`beta`, không gửi tool call sang mini | mitigate | Model Gateway | G6 phải có `incompatible_routes=0` và availability ≥ 0.95 trên ba seed |

## 7. Điểm yếu còn lại

G2 của resilient client vẫn có p95 10.362 giây, cao hơn các băng khác, và cost/turn 2.108 vì `alpha-eu`/`beta` phải gánh tải trong lúc primary suy giảm. Nếu cả bốn provider cùng chậm nhưng chưa lỗi, các breaker có thể cùng mở và làm availability phụ thuộc vào cache chỉ dành cho FAQ. Bước tiếp theo là adaptive concurrency limit theo queue latency, hedging có budget cho request đọc thuần và tách deadline theo từng rung fallback; các thay đổi phải được gate bằng amplification, chi phí và availability trên nhiều seed.

## 8. Cache — Part G

| Client | availability | faq_availability | cache_hit_ratio | stale_served | wrong_answers | outdated_answers | cost/turn | PASS? |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| resilient, không cache | 0.8373 | 0.8424 | 0.000 | 0 | 0 | 0 | 1.386 | Không |
| cached | 0.9124 | 0.9645 | 0.652 | 157 | 0 | 3 | 0.915 | Có |

| Tham số `cache:` | Giá trị | Lý do dựa trên số liệu |
|---|---:|---|
| `similarity_threshold` | 0.90 | 0.80 tạo 175 câu trả lời sai do `other_question`; 0.90 giữ `wrong_answers=0`, hit 0.652 và cost 0.915. Mức 0.97 cũng đúng nhưng hit giảm còn 0.579 và cost tăng 0.965. |
| `ttl_s` | 60 | TTL 60 cho 3 outdated, hit 0.652, cost 0.915. TTL 30 giảm outdated còn 2 nhưng hit 0.592/cost 0.955; TTL 300 tạo 95 outdated và fail rubric. |
| `max_stale_s` | 600 | Bao phủ outage 120 giây: phục vụ 157 stale và FAQ availability 0.9645. Đặt 0 làm FAQ availability giảm còn 0.8733. |

**Thí nghiệm ngưỡng.** Ở 0.80, hit 0.659 nhưng có 175 `other_question`, chủ yếu do các cặp gần mà khác nghĩa như refund policy/refund time, đổi size/đổi màu và phí ship nội thành/ngoại tỉnh. Ở 0.90, hit 0.652, sai 0, cost 0.915. Ở 0.97, hit giảm 0.579, sai vẫn 0 và cost tăng 0.965; vì vậy 0.90 là điểm cân bằng.

**Thí nghiệm TTL.** TTL 30/60/300 lần lượt cho outdated 2/3/95, hit 0.592/0.652/0.731 và cost 0.955/0.915/0.863. Webhook chỉ invalidate thay đổi `policy/refund` đã được báo; thay đổi giá ship ở t=480 là silent update nên webhook không biết để xóa. TTL là giới hạn duy nhất cho thời gian câu trả lời âm thầm lỗi thời, vì vậy chọn 60 giây để outdated=3, thấp hơn ngưỡng 15.

**Stale-if-error.** Với `max_stale_s=0`, FAQ availability chỉ 0.8733 và stale served bằng 0. Bật cửa sổ 600 giây nâng FAQ availability lên 0.9645, phục vụ 157 câu stale trong outage mà vẫn `wrong_answers=0` nhờ scope prompt version và invalidation.

Câu hỏi cá nhân không cache kể cả theo user vì dữ liệu đơn hàng/hoàn tiền thay đổi nhanh, nhạy cảm và phụ thuộc quyền truy cập tại thời điểm đọc. Một lỗi khóa tenant, tái sử dụng user ID hoặc thu hồi quyền có thể biến cache thành rò rỉ dữ liệu; request trực tiếp tới nguồn có thẩm quyền an toàn hơn.

Trong outage, dashboard user-facing có thể xanh nhờ cache nên on-call phải theo dõi riêng: tỷ lệ request tới provider thành công, số breaker OPEN, provider error/timeout, `stale_served` và tuổi stale. Ở C1, spike **157 stale serves** là tín hiệu rõ rằng hệ thống đang chạy ở chế độ suy giảm dù FAQ availability vẫn 96.45%.
