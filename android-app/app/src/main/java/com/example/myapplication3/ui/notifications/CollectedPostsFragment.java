package com.example.myapplication3.ui.notifications;

import android.os.Bundle;
import android.view.Gravity;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;

import com.example.myapplication3.MainActivity;
import com.example.myapplication3.R;

public class CollectedPostsFragment extends Fragment {

    public CollectedPostsFragment() {
    }

    @Override
    public View onCreateView(
            @NonNull LayoutInflater inflater,
            ViewGroup container,
            Bundle savedInstanceState
    ) {
        View root = inflater.inflate(R.layout.fragment_collected_posts, container, false);

        Button menuButton = root.findViewById(R.id.menu_button);
        menuButton.setOnClickListener(v -> openDrawer());

        loadCollectedPosts(root);
        return root;
    }

    private void openDrawer() {
        if (getActivity() instanceof MainActivity) {
            MainActivity activity = (MainActivity) getActivity();
            activity.openDrawer();
        }
    }

    private void loadCollectedPosts(View root) {
        LinearLayout container = root.findViewById(R.id.collected_posts_container);
        container.removeAllViews();

        TextView notice = new TextView(getContext());
        notice.setText("收藏功能已移除");
        notice.setTextSize(16);
        notice.setTextColor(ContextCompat.getColor(requireContext(), android.R.color.darker_gray));
        notice.setGravity(Gravity.CENTER);
        notice.setPadding(0, 48, 0, 0);
        container.addView(notice);
    }

    @Override
    public void onResume() {
        super.onResume();
        if (getView() != null) {
            loadCollectedPosts(getView());
        }
    }
}
