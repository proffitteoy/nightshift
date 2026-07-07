package com.example.myapplication3.network;

import com.example.myapplication3.network.models.AuthLoginRequest;
import com.example.myapplication3.network.models.AuthChangePasswordRequest;
import com.example.myapplication3.network.models.AuthRegisterRequest;
import com.example.myapplication3.network.models.AuthTokenResponse;
import com.example.myapplication3.network.models.DailyReportResponse;
import com.example.myapplication3.network.models.DeepAnalysisRequest;
import com.example.myapplication3.network.models.DeepAnalysisResponse;
import com.example.myapplication3.network.models.GitHubOAuthPollResponse;
import com.example.myapplication3.network.models.GitHubOAuthStartResponse;
import com.example.myapplication3.network.models.ReportQaResponse;
import com.example.myapplication3.network.models.RepoSubscriptionRequest;
import com.example.myapplication3.network.models.RuntimeConfigResponse;
import com.example.myapplication3.network.models.SubscriptionResponse;
import com.example.myapplication3.network.models.TrendingAnalysisResponse;
import com.example.myapplication3.network.models.TrendingDetailSummaryRequest;
import com.example.myapplication3.network.models.TrendingDetailSummaryResponse;
import com.example.myapplication3.network.models.UserProfileResponse;

import java.util.List;
import java.util.Map;

import okhttp3.ResponseBody;
import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.DELETE;
import retrofit2.http.GET;
import retrofit2.http.POST;
import retrofit2.http.PUT;
import retrofit2.http.Path;

public interface ApiService {

    @POST("auth/login")
    Call<AuthTokenResponse> login(@Body AuthLoginRequest request);

    @POST("auth/register")
    Call<AuthTokenResponse> register(@Body AuthRegisterRequest request);

    @POST("auth/change-password")
    Call<Map<String, Object>> changePassword(@Body AuthChangePasswordRequest request);

    @POST("auth/github/start")
    Call<GitHubOAuthStartResponse> startGitHubOAuth();

    @GET("auth/github/poll/{poll_token}")
    Call<GitHubOAuthPollResponse> pollGitHubOAuth(@Path("poll_token") String pollToken);

    @GET("me")
    Call<UserProfileResponse> getMe();

    @GET("api/health")
    Call<Map<String, Object>> getHealth();

    /**
     * 根据用户输入的仓库地址生成晨间简报
     */
    @POST("api/project/report-by-user")
    Call<DailyReportResponse> generateDailyReport(@Body RepoSubscriptionRequest request);

    /**
     * 读取最近一次标准化晨报
     */
    @GET("api/project/daily-report")
    Call<DailyReportResponse.DailyReport> getLatestDailyReport();

    /**
     * 基于当前晨报继续追问
     */
    @POST("api/project/report-qa")
    Call<ReportQaResponse> askReportQuestion(@Body Map<String, Object> request);

    /**
     * 获取一周热点项目分析结果
     */
    @GET("api/trending/generate-analysis")
    Call<TrendingAnalysisResponse> getTrendingAnalysis();

    /**
     * 为热点详情生成单独的两段式解读
     */
    @POST("api/trending/detail-summary")
    Call<TrendingDetailSummaryResponse> getTrendingDetailSummary(@Body TrendingDetailSummaryRequest request);

    /**
     * 获取订阅列表
     */
    @GET("api/subscriptions")
    Call<List<SubscriptionResponse>> getSubscriptions();

    /**
     * 创建订阅
     */
    @POST("api/subscriptions")
    Call<SubscriptionResponse> createSubscription(@Body Map<String, Object> request);

    /**
     * 更新订阅
     */
    @PUT("api/subscriptions/{subscription_id}")
    Call<SubscriptionResponse> updateSubscription(@Path("subscription_id") int subscriptionId, @Body Map<String, Object> request);

    /**
     * 删除订阅
     */
    @POST("api/subscriptions/{subscription_id}/send")
    Call<Map<String, Object>> sendSubscription(@Path("subscription_id") int subscriptionId);

    @DELETE("api/subscriptions/{subscription_id}")
    Call<ResponseBody> deleteSubscription(@Path("subscription_id") int subscriptionId);

    /**
     * 读取运行时配置
     */
    @GET("api/subscriptions/runtime-config")
    Call<RuntimeConfigResponse> getRuntimeConfig();

    /**
     * 保存运行时配置
     */
    @PUT("api/subscriptions/runtime-config")
    Call<RuntimeConfigResponse> updateRuntimeConfig(@Body Map<String, Object> request);

    @DELETE("api/subscriptions/runtime-config")
    Call<RuntimeConfigResponse> clearRuntimeConfig();
}

    /**
     * 调用工作流对 GitHub 项目进行深度分析
     */
    @POST("api/project/deep-analysis")
    Call<DeepAnalysisResponse> deepAnalysis(@Body DeepAnalysisRequest request);

}
